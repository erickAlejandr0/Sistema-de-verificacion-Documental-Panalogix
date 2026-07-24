"""Handler de alertas de vencimiento documental (M-ALERT / P4.3).

Invocado por EventBridge (cron). Orquesta avisos a 30, 7 y 0 días.

Garantías:
    - ``documentos_por_vencer`` ya filtra ``resultado = APROBADO`` en SQL
      (P2.3); este handler **no** refiltra en Python. Por tanto
      ``AlertaPublicacion.resultado`` es **siempre** ``APROBADO``.
    - Clasificación exacta de umbrales (30 / 7 / ≤0) con
      ``days_until_expiry`` en zona America/Panama.
    - Idempotencia de publicación: mismo protocolo P4.2
      (``try_registrar_alerta`` + ``enviada_en``). El SVD no suspende
      transportistas; ``vencimiento_critico`` es señal para Panalogix.
"""

from __future__ import annotations

from typing import Any

from app.models.alerta import Alerta, AlertaCreate
from app.models.documento import Documento
from app.models.enums import DiasAviso, EstadoAlerta, ResultadoVerificacion
from app.models.historial import Historial
from app.models.notificacion import AlertaPublicacion, decimal_score_to_str
from app.repositories.exceptions import DocumentNotFoundError
from app.repositories.verificacion import VerificacionRepository
from app.services.sns import NonRetryableNotificationError, NotificationService
from app.utils.dates import days_until_expiry
from app.utils.logging import get_logger
from app.utils.tracing import configure_xray

configure_xray()

logger = get_logger(__name__)

_VENTANA_DIAS: int = 30

_EVENT_BY_THRESHOLD: dict[DiasAviso, str] = {
    DiasAviso.THIRTY: "alerta_vencimiento_30",
    DiasAviso.SEVEN: "alerta_vencimiento_7",
    DiasAviso.ZERO: "vencimiento_critico",
}


def _classify_threshold(days_remaining: int) -> DiasAviso | None:
    """Mapea días restantes al umbral exacto, o ``None`` si no aplica hoy.

    Args:
        days_remaining: ``fecha_vencimiento - hoy`` (America/Panama).

    Returns:
        ``DiasAviso`` si coincide con 30, 7 o ≤0; ``None`` en otro caso.
    """
    if days_remaining == int(DiasAviso.THIRTY):
        return DiasAviso.THIRTY
    if days_remaining == int(DiasAviso.SEVEN):
        return DiasAviso.SEVEN
    if days_remaining <= int(DiasAviso.ZERO):
        return DiasAviso.ZERO
    return None


def _tipo_documento(documento: Documento, historial: Historial) -> str:
    """Prefiere tipo_detectado; cae al tipo declarado del documento."""
    detected = (historial.tipo_detectado or "").strip()
    return detected if detected else documento.tipo_documento


class ExpirationAlertPipeline:
    """Orquestador inyectable de alertas de vencimiento."""

    def __init__(
        self,
        *,
        verificacion_repo: VerificacionRepository | None = None,
        notifications: NotificationService | None = None,
    ) -> None:
        """Inicializa repositorio y servicio SNS."""
        self._repo = verificacion_repo or VerificacionRepository()
        self._notifications = notifications or NotificationService()

    def run(self) -> dict[str, int]:
        """Consulta candidatos, clasifica y publica alertas pendientes.

        Returns:
            Contadores ``candidatos``, ``publicadas``, ``omitidas``, ``errores``.
        """
        candidatos = self._repo.documentos_por_vencer(_VENTANA_DIAS)
        published = 0
        skipped = 0
        errors = 0

        logger.info(
            "expiration_scan_start",
            extra={"context": {"candidatos": len(candidatos), "ventana_dias": _VENTANA_DIAS}},
        )

        for historial in candidatos:
            if historial.fecha_vencimiento is None:
                skipped += 1
                continue

            days_remaining = days_until_expiry(historial.fecha_vencimiento)
            threshold = _classify_threshold(days_remaining)
            if threshold is None:
                skipped += 1
                continue

            try:
                sent = self._dispatch_alerta(historial, threshold, days_remaining)
            except NonRetryableNotificationError as exc:
                errors += 1
                logger.error(
                    "expiration_sns_non_retryable",
                    extra={
                        "context": {
                            "historial_id": str(historial.id),
                            "documento_id": str(historial.documento_id),
                            "dias_aviso": int(threshold),
                            "error": type(exc).__name__,
                        }
                    },
                )
                continue
            except DocumentNotFoundError:
                errors += 1
                logger.warning(
                    "expiration_documento_ausente",
                    extra={
                        "context": {
                            "historial_id": str(historial.id),
                            "documento_id": str(historial.documento_id),
                            "dias_aviso": int(threshold),
                        }
                    },
                )
                continue

            if sent:
                published += 1
            else:
                skipped += 1

        summary = {
            "candidatos": len(candidatos),
            "publicadas": published,
            "omitidas": skipped,
            "errores": errors,
        }
        logger.info("expiration_scan_done", extra={"context": summary})
        return summary

    def _dispatch_alerta(
        self,
        historial: Historial,
        threshold: DiasAviso,
        days_remaining: int,
    ) -> bool:
        """Aplica protocolo ``enviada_en`` y publica si corresponde.

        Args:
            historial: Extracción APROBADO (garantía SQL).
            threshold: Umbral clasificado.
            days_remaining: Días hasta vencimiento (logging).

        Returns:
            ``True`` si se publicó en SNS; ``False`` si se omitió.

        Raises:
            DocumentNotFoundError: Documento físico ausente.
            NonRetryableNotificationError: Fallo SNS no reintentable.
            RetryableNotificationError / RepositoryError: Propagados.
        """
        dias_aviso = int(threshold)
        event_type = _EVENT_BY_THRESHOLD[threshold]

        inserted = self._repo.try_registrar_alerta(
            AlertaCreate(
                historial_id=historial.id,
                dias_aviso=threshold,
                estado=EstadoAlerta.PENDIENTE,
            )
        )
        alerta: Alerta | None = inserted
        if alerta is None:
            alerta = self._repo.obtener_alerta(historial.id, dias_aviso)

        if alerta is None:
            logger.error(
                "expiration_alerta_no_encontrada",
                extra={
                    "context": {
                        "historial_id": str(historial.id),
                        "dias_aviso": dias_aviso,
                        "days_remaining": days_remaining,
                    }
                },
            )
            return False

        if alerta.enviada_en is not None:
            logger.info(
                "expiration_alerta_ya_enviada",
                extra={
                    "context": {
                        "historial_id": str(historial.id),
                        "documento_id": str(historial.documento_id),
                        "dias_aviso": dias_aviso,
                        "days_remaining": days_remaining,
                        "alerta_enviada": True,
                    }
                },
            )
            return False

        documento = self._repo.obtener_documento(historial.documento_id)
        payload = AlertaPublicacion(
            transportista_id=documento.transportista_id,
            tipo_documento=_tipo_documento(documento, historial),
            resultado=ResultadoVerificacion.APROBADO.value,
            score_lectura=decimal_score_to_str(historial.score_lectura),
            score_autenticidad=decimal_score_to_str(historial.score_autenticidad),
            fecha_vencimiento=historial.fecha_vencimiento,
        )
        message_id = self._notifications.publicar_alerta(
            payload,
            dias_aviso=dias_aviso,
            event_type=event_type,
        )
        self._repo.marcar_alerta_enviada(alerta.id)
        logger.info(
            "expiration_sns_alerta",
            extra={
                "context": {
                    "historial_id": str(historial.id),
                    "documento_id": str(historial.documento_id),
                    "dias_aviso": dias_aviso,
                    "days_remaining": days_remaining,
                    "event_type": event_type,
                    "sns_message_id": message_id,
                    "alerta_enviada": True,
                }
            },
        )
        return True


def handler(event: dict[str, Any], context: object) -> dict[str, Any]:
    """Punto de entrada Lambda (EventBridge schedule).

    Args:
        event: Evento EventBridge (ignorado en MVP).
        context: Contexto Lambda (ignorado).

    Returns:
        Resumen de la corrida (contadores).
    """
    del event, context
    pipeline = ExpirationAlertPipeline()
    return pipeline.run()
