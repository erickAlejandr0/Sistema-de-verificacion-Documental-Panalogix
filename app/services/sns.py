"""Servicio de publicación de resultados y alertas en SNS.

Fan-out desacoplado hacia webhook Panalogix y otros suscriptores
(RF-16, RF-17, RF-18, RF-19). No conoce a los suscriptores.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.models.notificacion import AlertaPublicacion, ResultadoPublicacion
from app.utils.logging import get_logger

logger = get_logger(__name__)

_EVENT_RESULTADO: str = "verificacion_resultado"

_RETRYABLE_SNS_CODES: frozenset[str] = frozenset(
    {
        "Throttling",
        "ThrottlingException",
        "ProvisionedThroughputExceededException",
        "ServiceUnavailable",
        "InternalError",
        "InternalFailure",
        "RequestTimeout",
        "RequestTimeoutException",
    }
)

_NON_RETRYABLE_SNS_CODES: frozenset[str] = frozenset(
    {
        "InvalidParameter",
        "InvalidParameterValue",
        "InvalidClientTokenId",
        "AuthorizationError",
        "NotFound",
        "AccessDenied",
        "AccessDeniedException",
        "OptInRequired",
        "ValidationError",
    }
)


class NotificationError(Exception):
    """Error base del servicio de notificaciones SNS."""


class RetryableNotificationError(NotificationError):
    """Error reintentable (throttling / 5xx / timeout) — SQS debe reintentar."""


class NonRetryableNotificationError(NotificationError):
    """Error no reintentable (ARN inválido, IAM, parámetros)."""


class _SnsJsonEncoder(json.JSONEncoder):
    """Encoder de defensa: Decimal→str, UUID→str, date→ISO, Enum→value."""

    def default(self, o: object) -> object:
        if isinstance(o, Decimal):
            return str(o)
        if isinstance(o, UUID):
            return str(o)
        if isinstance(o, datetime):
            return o.isoformat()
        if isinstance(o, date):
            return o.isoformat()
        if isinstance(o, Enum):
            return o.value
        return super().default(o)


def _serialize_body(body: dict[str, Any]) -> str:
    """Serializa el body SNS a JSON con encoder de defensa."""
    return json.dumps(body, ensure_ascii=False, cls=_SnsJsonEncoder)


def _sns_error_code(exc: ClientError) -> str:
    """Extrae el código de error de un ClientError de botocore."""
    response = getattr(exc, "response", None) or {}
    error = response.get("Error") or {}
    return str(error.get("Code") or "")


class NotificationService:
    """Publica resultados y alertas en un topic SNS (fan-out).

    Args:
        client: Cliente boto3 SNS inyectable (tests).
        topic_arn: ARN del topic. Si es ``None``, desde settings.
        region_name: Región AWS. Si es ``None``, desde settings.
    """

    def __init__(
        self,
        *,
        client: object | None = None,
        topic_arn: str | None = None,
        region_name: str | None = None,
    ) -> None:
        """Inicializa el servicio con topic y cliente SNS."""
        if topic_arn is None or region_name is None:
            from app.config import get_common_settings

            if topic_arn is None:
                topic_arn = get_common_settings().aws_sns_topic_arn
            if region_name is None:
                region_name = get_common_settings().aws_region

        self._topic_arn = topic_arn
        self._client = client or boto3.client("sns", region_name=region_name)

    def publicar_resultado(self, payload: ResultadoPublicacion) -> str:
        """Publica el resultado de una verificación en el topic SNS.

        Body JSON: los 6 campos de ``ResultadoPublicacion``.
        MessageAttributes: ``event_type=verificacion_resultado`` y
        ``resultado`` para filtrado de suscriptores.

        Args:
            payload: Contrato externo ya armado por el orquestador.

        Returns:
            ``MessageId`` de SNS solo para trazabilidad/auditoría del
            orquestador (correlacionar mensaje ↔ verificación). No se
            persiste en BD en P4.1.

        Raises:
            RetryableNotificationError: Throttling, 5xx o timeout.
            NonRetryableNotificationError: ARN/IAM/parámetros inválidos.
        """
        body = payload.model_dump(mode="json")
        attributes = {
            "event_type": {
                "DataType": "String",
                "StringValue": _EVENT_RESULTADO,
            },
            "resultado": {
                "DataType": "String",
                "StringValue": payload.resultado,
            },
        }
        return self._publish(
            body=body,
            attributes=attributes,
            log_event="sns_resultado_publicado",
            log_context={
                "event_type": _EVENT_RESULTADO,
                "resultado": payload.resultado,
                "transportista_id": str(payload.transportista_id),
                "tipo_documento": payload.tipo_documento,
            },
        )

    def publicar_alerta(
        self,
        payload: AlertaPublicacion,
        *,
        dias_aviso: int,
        event_type: str,
    ) -> str:
        """Publica una alerta de vencimiento o revisión manual.

        Body JSON: los 6 campos de ``AlertaPublicacion`` **más**
        ``dias_aviso`` y ``event_type`` combinados internamente
        (``{**payload.model_dump(mode="json"), "dias_aviso": ...,
        "event_type": ...}``). MessageAttributes llevan los mismos
        ``event_type`` / ``dias_aviso`` solo para filtro SNS; no
        sustituyen al body.

        Args:
            payload: Contrato externo (6 campos de correlación).
            dias_aviso: Umbral RF-18 (30, 7 o 0) u otro entero de negocio.
            event_type: Tipo de evento (p. ej. ``alerta_vencimiento``,
                ``revision_manual``).

        Returns:
            ``MessageId`` de SNS solo para trazabilidad/auditoría del
            orquestador (correlacionar mensaje ↔ alerta). No se
            persiste en BD en P4.1.

        Raises:
            RetryableNotificationError: Throttling, 5xx o timeout.
            NonRetryableNotificationError: ARN/IAM/parámetros inválidos.
        """
        body = {
            **payload.model_dump(mode="json"),
            "dias_aviso": dias_aviso,
            "event_type": event_type,
        }
        attributes = {
            "event_type": {
                "DataType": "String",
                "StringValue": event_type,
            },
            "dias_aviso": {
                "DataType": "Number",
                "StringValue": str(dias_aviso),
            },
        }
        return self._publish(
            body=body,
            attributes=attributes,
            log_event="sns_alerta_publicada",
            log_context={
                "event_type": event_type,
                "dias_aviso": dias_aviso,
                "resultado": payload.resultado,
                "transportista_id": str(payload.transportista_id),
                "tipo_documento": payload.tipo_documento,
            },
        )

    def _publish(
        self,
        *,
        body: dict[str, Any],
        attributes: dict[str, dict[str, str]],
        log_event: str,
        log_context: dict[str, Any],
    ) -> str:
        """Ejecuta ``Publish`` y clasifica errores SNS."""
        message = _serialize_body(body)
        try:
            response = self._client.publish(
                TopicArn=self._topic_arn,
                Message=message,
                MessageAttributes=attributes,
            )
        except ClientError as exc:
            self._raise_classified(exc, log_context)
        except BotoCoreError as exc:
            logger.error(
                "sns_publish_network_error",
                extra={
                    "context": {
                        **log_context,
                        "error": type(exc).__name__,
                    }
                },
            )
            raise RetryableNotificationError(
                "error de red/timeout al publicar en SNS"
            ) from exc

        message_id = str(response.get("MessageId") or "")
        if not message_id:
            logger.error(
                "sns_publish_sin_message_id",
                extra={"context": log_context},
            )
            raise NonRetryableNotificationError(
                "SNS no devolvió MessageId"
            )

        logger.info(
            log_event,
            extra={"context": {**log_context, "message_id": message_id}},
        )
        return message_id

    def _raise_classified(
        self,
        exc: ClientError,
        log_context: dict[str, Any],
    ) -> None:
        """Clasifica ClientError y propaga (nunca silencia)."""
        code = _sns_error_code(exc)
        context = {**log_context, "error": type(exc).__name__, "aws_code": code}

        if code in _RETRYABLE_SNS_CODES:
            logger.warning(
                "sns_publish_retryable",
                extra={"context": context},
            )
            raise RetryableNotificationError(
                f"SNS reintentable ({code})"
            ) from exc

        if code in _NON_RETRYABLE_SNS_CODES or code.startswith("Invalid"):
            logger.error(
                "sns_publish_non_retryable",
                extra={"context": context},
            )
            raise NonRetryableNotificationError(
                f"SNS no reintentable ({code or 'desconocido'})"
            ) from exc

        # Códigos desconocidos: asumir retryable (transitorio) y dejar traza.
        logger.warning(
            "sns_publish_unknown_code_retryable",
            extra={"context": context},
        )
        raise RetryableNotificationError(
            f"SNS error desconocido tratado como reintentable ({code})"
        ) from exc
