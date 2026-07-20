"""Emisor de webhooks firmados hacia un receptor HTTPS configurable (M-WEBHOOK).

Suscriptor lógico del SNS Topic de resultados/alertas. POST-ea el Message SNS
como bytes crudos (sin re-serializar, para no romper la verificación HMAC del
receptor), firma HMAC-SHA256 y reintenta con backoff exponencial.

Desacoplado del pipeline SVD (P4.2): un receptor ausente o caído no es falla
crítica del sistema. Tras agotar reintentos se loguea ERROR y se retorna
``False`` sin propagar excepción.

Infra SAM (prompt futuro): el ``Timeout`` de esta Lambda debe cubrir el peor
caso de reintentos — backoff ``1+2+4 = 7s`` más hasta 3 timeouts HTTP de 10s
≈ **37s**. Usar margen (p. ej. **60s**) para no truncar a mitad de un reintento.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import urllib.error
import urllib.request
from typing import Any, Callable
from urllib.parse import urlparse

from app.utils.logging import get_logger

logger = get_logger(__name__)

_USER_AGENT = "svd-webhook/1.0"
_BACKOFF_SECONDS: tuple[float, ...] = (1.0, 2.0, 4.0)
_RETRYABLE_STATUS: frozenset[int] = frozenset({408, 429})


def sign_body(secret: str, body: bytes) -> str:
    """Calcula la firma HMAC-SHA256 del body crudo.

    Args:
        secret: Secreto compartido (UTF-8).
        body: Bytes exactos del POST.

    Returns:
        Cadena ``sha256=<hex lowercase>`` para el header ``X-SVD-Signature``.
    """
    digest = hmac.new(
        secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()
    return f"sha256={digest}"


def _log_host(url: str) -> str:
    """Host del URL para logs (nunca URL completa ni secreto)."""
    try:
        return urlparse(url).hostname or "unknown-host"
    except ValueError:
        return "unknown-host"


def _should_retry_status(status: int) -> bool:
    """True si el código HTTP justifica otro intento."""
    if status in _RETRYABLE_STATUS:
        return True
    return 500 <= status <= 599


class WebhookService:
    """Entrega HTTPS firmada del contrato SNS hacia el endpoint configurado.

    Args:
        url: URL HTTPS del receptor. Si es ``None``, desde settings.
        secret: Secreto HMAC. Si es ``None``, desde settings.
        timeout_seconds: Timeout por intento.
        max_attempts: Intentos totales (ver nota de Timeout Lambda en módulo).
        sleep: Callable de espera inyectable (tests).
        urlopen: Callable HTTP inyectable (tests); firma compatible con
            ``urllib.request.urlopen``.
    """

    def __init__(
        self,
        *,
        url: str | None = None,
        secret: str | None = None,
        timeout_seconds: float | None = None,
        max_attempts: int | None = None,
        sleep: Callable[[float], None] | None = None,
        urlopen: Callable[..., object] | None = None,
    ) -> None:
        """Inicializa el emisor con destino y secreto."""
        if (
            url is None
            or secret is None
            or timeout_seconds is None
            or max_attempts is None
        ):
            from app.config import get_webhook_settings

            settings = get_webhook_settings()
            if url is None:
                url = settings.webhook_url
            if secret is None:
                secret = settings.webhook_hmac_secret
            if timeout_seconds is None:
                timeout_seconds = settings.webhook_timeout_seconds
            if max_attempts is None:
                max_attempts = settings.webhook_max_attempts

        self._url = url
        self._secret = secret
        self._timeout = float(timeout_seconds)
        self._max_attempts = int(max_attempts)
        self._sleep = sleep or time.sleep
        self._urlopen = urlopen or urllib.request.urlopen

    def deliver(self, *, body: bytes | str, event_type: str) -> bool:
        """POST firmado del body crudo hacia el webhook.

        Args:
            body: Payload JSON como bytes o str UTF-8 (sin re-serializar).
            event_type: Valor del header ``X-SVD-Event-Type``.

        Returns:
            ``True`` si algún intento recibió 2xx; ``False`` tras agotar
            retries o ante 4xx no reintentable (sin raise).
        """
        raw = body if isinstance(body, bytes) else body.encode("utf-8")
        signature = sign_body(self._secret, raw)
        host = _log_host(self._url)

        last_status: int | None = None
        last_error: str | None = None

        for attempt in range(1, self._max_attempts + 1):
            try:
                status = self._post_once(
                    raw=raw,
                    signature=signature,
                    event_type=event_type,
                )
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = type(exc).__name__
                last_status = None
                logger.warning(
                    "webhook_attempt_network_error",
                    extra={
                        "context": {
                            "host": host,
                            "attempt": attempt,
                            "max_attempts": self._max_attempts,
                            "error": last_error,
                            "event_type": event_type,
                        }
                    },
                )
                if attempt < self._max_attempts:
                    self._backoff(attempt)
                continue

            last_status = status
            if 200 <= status <= 299:
                logger.info(
                    "webhook_delivered",
                    extra={
                        "context": {
                            "host": host,
                            "attempt": attempt,
                            "status": status,
                            "event_type": event_type,
                        }
                    },
                )
                return True

            if _should_retry_status(status):
                logger.warning(
                    "webhook_attempt_retryable_status",
                    extra={
                        "context": {
                            "host": host,
                            "attempt": attempt,
                            "max_attempts": self._max_attempts,
                            "status": status,
                            "event_type": event_type,
                        }
                    },
                )
                if attempt < self._max_attempts:
                    self._backoff(attempt)
                continue

            logger.warning(
                "webhook_non_retryable_status",
                extra={
                    "context": {
                        "host": host,
                        "attempt": attempt,
                        "status": status,
                        "event_type": event_type,
                    }
                },
            )
            return False

        logger.error(
            "webhook_delivery_exhausted",
            extra={
                "context": {
                    "host": host,
                    "max_attempts": self._max_attempts,
                    "last_status": last_status,
                    "last_error": last_error,
                    "event_type": event_type,
                }
            },
        )
        return False

    def deliver_from_sns_record(self, record: dict[str, Any]) -> bool:
        """Entrega el Message de un record SNS Lambda sin re-serializar.

        Args:
            record: Elemento de ``event["Records"]`` (shape SNS).

        Returns:
            Resultado de ``deliver``.
        """
        sns = record.get("Sns") or {}
        if not isinstance(sns, dict):
            logger.error(
                "webhook_invalid_sns_record",
                extra={"context": {"detalle": "Sns ausente o inválido"}},
            )
            return False

        message = sns.get("Message")
        if message is None:
            logger.error(
                "webhook_missing_message",
                extra={"context": {"detalle": "Message vacío"}},
            )
            return False

        # Bytes crudos del Message SNS (str en el envelope Lambda).
        if isinstance(message, bytes):
            raw = message
        else:
            raw = str(message).encode("utf-8")

        event_type = self._event_type_from_record(sns, raw)
        return self.deliver(body=raw, event_type=event_type)

    def _post_once(
        self,
        *,
        raw: bytes,
        signature: str,
        event_type: str,
    ) -> int:
        """Ejecuta un POST; retorna status HTTP (incl. errores HTTP)."""
        request = urllib.request.Request(
            self._url,
            data=raw,
            method="POST",
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "X-SVD-Event-Type": event_type,
                "X-SVD-Signature": signature,
                "User-Agent": _USER_AGENT,
            },
        )
        try:
            with self._urlopen(request, timeout=self._timeout) as response:
                status = int(getattr(response, "status", None) or response.getcode())
                # Drenar body para liberar conexión; ignorar contenido.
                try:
                    response.read()
                except OSError:
                    pass
                return status
        except urllib.error.HTTPError as exc:
            return int(exc.code)

    def _backoff(self, attempt: int) -> None:
        """Espera según intento 1-based (1→1s, 2→2s, 3→4s, …)."""
        index = min(attempt - 1, len(_BACKOFF_SECONDS) - 1)
        self._sleep(_BACKOFF_SECONDS[index])

    @staticmethod
    def _event_type_from_record(sns: dict[str, Any], raw: bytes) -> str:
        """Resuelve event_type desde MessageAttributes o body JSON."""
        attrs = sns.get("MessageAttributes") or {}
        if isinstance(attrs, dict):
            et = attrs.get("event_type") or attrs.get("Event_Type")
            if isinstance(et, dict):
                value = et.get("Value") or et.get("StringValue")
                if value:
                    return str(value)

        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            return "unknown"
        if isinstance(parsed, dict) and parsed.get("event_type"):
            return str(parsed["event_type"])
        return "verificacion_resultado"
