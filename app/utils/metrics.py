"""Emisión de métricas CloudWatch Embedded Metric Format (EMF).

Las líneas EMF son entradas de log **separadas** del ``JsonFormatter``
habitual: nunca se mezclan ``_aws`` con el payload de logging estructurado.

No usa ``put_metric_data`` (basta ``logs:PutLogEvents``). Fallos de
serialización/emisión se absorben — las métricas no deben tumbar el job.

``campos_tipicos`` / ``emisor`` (estructura de patrones) no son métricas:
son texto/estructura; consultar RDS / historial.
"""

from __future__ import annotations

import json
import time
from typing import Any

from app.services.field_applicability import DEFAULT_CAMPOS_APLICABLES
from app.utils.logging import get_logger

logger = get_logger(__name__)

NAMESPACE: str = "SVD"

# Unión de labels canónicos (vocabulario cerrado). Cardinalidad acotada para
# la dimensión EMF ``campo_corregido``; el valor libre sigue en RDS.
_KNOWN_CAMPO_LABELS: frozenset[str] = frozenset(
    label
    for labels in DEFAULT_CAMPOS_APLICABLES.values()
    for label in labels
)
_OTHER_CAMPO: str = "other"


def normalize_campo_corregido_dimension(raw: str) -> str:
    """Normaliza ``campo_corregido`` para dimensión EMF (cardinalidad acotada).

    El body de ``/resolver`` sigue aceptando texto libre; solo la dimensión
    de métrica se restringe al vocabulario canónico o ``other``.

    Args:
        raw: Nombre de campo enviado por Retool.

    Returns:
        Label canónico o ``other``.
    """
    campo = (raw or "").strip().casefold()
    if campo in _KNOWN_CAMPO_LABELS:
        return campo
    return _OTHER_CAMPO


def emit_count(
    metric_name: str,
    value: float = 1.0,
    *,
    dimensions: dict[str, str],
    unit: str = "Count",
) -> None:
    """Emite un contador EMF a stdout (línea JSON independiente).

    Args:
        metric_name: Nombre de la métrica CloudWatch.
        value: Incremento (default 1).
        dimensions: Pares nombre→valor (sin PII).
        unit: Unidad EMF (default Count).
    """
    _emit(metric_name, value, dimensions=dimensions, unit=unit)


def emit_value(
    metric_name: str,
    value: float,
    *,
    dimensions: dict[str, str],
    unit: str = "None",
) -> None:
    """Emite un valor gauge/serie EMF a stdout.

    Args:
        metric_name: Nombre de la métrica CloudWatch.
        value: Valor numérico (p. ej. confianza promedio tras upsert).
        dimensions: Pares nombre→valor (sin PII).
        unit: Unidad EMF (default None).
    """
    _emit(metric_name, value, dimensions=dimensions, unit=unit)


def _emit(
    metric_name: str,
    value: float,
    *,
    dimensions: dict[str, str],
    unit: str,
) -> None:
    """Construye y escribe una línea EMF; nunca propaga excepciones."""
    try:
        dim_names = list(dimensions.keys())
        payload: dict[str, Any] = {
            "_aws": {
                "Timestamp": int(time.time() * 1000),
                "CloudWatchMetrics": [
                    {
                        "Namespace": NAMESPACE,
                        "Dimensions": [dim_names],
                        "Metrics": [{"Name": metric_name, "Unit": unit}],
                    }
                ],
            },
            metric_name: float(value),
        }
        for key, dim_value in dimensions.items():
            payload[key] = str(dim_value)
        print(json.dumps(payload, ensure_ascii=False, default=str), flush=True)
    except Exception as exc:
        logger.warning(
            "metrics_emit_failed",
            extra={
                "context": {
                    "metric_name": metric_name,
                    "error": type(exc).__name__,
                }
            },
        )
