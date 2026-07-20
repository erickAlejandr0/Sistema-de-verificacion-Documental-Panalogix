"""Handler Lambda suscriptor SNS → emisor webhook (M-WEBHOOK).

Orquesta únicamente: unwrap del envelope SNS e invocación de
``WebhookService``. Los fallos de entrega HTTP se absorben (ack SNS); no
se re-lanzan como error crítico del SVD.

Riesgo residual aceptado (``MaximumRetryAttempts: 1`` en SAM): si la
Lambda hace timeout **después** de que ``webhook_service`` ya entregó
2xx al receptor pero **antes** de retornar, el reintento de invocación
puede reenviar un POST ya entregado. Baja probabilidad; inherente a
reintentos async + llamada externa no idempotente. Se acepta a cambio
de una segunda oportunidad ante bug/OOM/timeout genuino antes de DLQ
(mismo criterio que S3 verified no atómico en P4.2).
"""

from __future__ import annotations

from typing import Any

from app.services.webhook_service import WebhookService
from app.utils.logging import get_logger

logger = get_logger(__name__)


def handler(event: dict[str, Any], context: object) -> dict[str, Any]:
    """Punto de entrada Lambda (trigger SNS).

    El ``try`` envuelve desde la primera línea ejecutable (incl. acceso a
    ``Records`` y construcción de ``WebhookService``) para que **ninguna**
    excepción se propague a SNS/Lambda async — evita un segundo juego de
    reintentos HTTP del servicio.

    Args:
        event: Evento SNS (``Records[*].Sns``).
        context: Contexto Lambda (ignorado).

    Returns:
        Resumen ``delivered`` / ``failed`` (siempre ack; sin raise).
    """
    try:
        del context
        records = event.get("Records") or []
        if not isinstance(records, list):
            records = []

        service = WebhookService()
        delivered = 0
        failed = 0

        for record in records:
            if not isinstance(record, dict):
                failed += 1
                continue
            try:
                ok = service.deliver_from_sns_record(record)
            except Exception as exc:
                # Defensa: nunca tumbar el batch SNS por un bug inesperado.
                failed += 1
                logger.error(
                    "webhook_handler_unexpected_error",
                    extra={"context": {"error": type(exc).__name__}},
                )
                continue
            if ok:
                delivered += 1
            else:
                failed += 1

        summary = {
            "ok": True,
            "delivered": delivered,
            "failed": failed,
            "total": len(records),
        }
        logger.info("webhook_handler_done", extra={"context": summary})
        return summary
    except Exception as exc:
        logger.error(
            "webhook_handler_fatal",
            extra={"context": {"error": type(exc).__name__}},
        )
        return {
            "ok": False,
            "delivered": 0,
            "failed": 0,
            "total": 0,
            "error": type(exc).__name__,
        }
