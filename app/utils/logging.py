"""Logging estructurado para operaciones del SVD.

Emite logs JSON sin PII en claro, alineados a CloudWatch / observabilidad.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

# Claves que nunca deben aparecer en logs (Ley 81 / PII).
_PII_KEYS: frozenset[str] = frozenset(
    {
        "cedula",
        "cédula",
        "nombre",
        "nombre_completo",
        "full_name",
        "national_id",
        "placa",
        "apellido",
        "apellidos",
        "telefono",
        "teléfono",
        "email",
        "correo",
        "direccion",
        "dirección",
    }
)


def _redact_pii(context: dict[str, Any]) -> dict[str, Any]:
    """Elimina o enmascara claves PII del contexto de log.

    Args:
        context: Diccionario de contexto a sanitizar.

    Returns:
        Copia del contexto sin valores PII.
    """
    sanitized: dict[str, Any] = {}
    for key, value in context.items():
        if key.lower() in _PII_KEYS:
            sanitized[key] = "[REDACTED]"
            continue
        if isinstance(value, dict):
            sanitized[key] = _redact_pii(value)
            continue
        sanitized[key] = value
    return sanitized


class JsonFormatter(logging.Formatter):
    """Formatea registros de log como una línea JSON compatible con CloudWatch."""

    def format(self, record: logging.LogRecord) -> str:
        """Serializa el registro a JSON estructurado.

        Args:
            record: Registro de logging de la biblioteca estándar.

        Returns:
            Cadena JSON con timestamp, level, module, message y context opcional.
        """
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "level": record.levelname,
            "module": record.name,
            "message": record.getMessage(),
        }

        raw_context = getattr(record, "context", None)
        if raw_context is not None:
            if isinstance(raw_context, dict):
                payload["context"] = _redact_pii(raw_context)
            else:
                payload["context"] = {"value": str(raw_context)}

        return json.dumps(payload, ensure_ascii=False, default=str)


def get_logger(name: str) -> logging.Logger:
    """Devuelve un logger configurado con salida JSON a stdout.

    Si el logger ya tiene handlers, no los duplica.

    Args:
        name: Nombre del logger (típicamente ``__name__`` del módulo).

    Returns:
        Logger listo para emitir logs estructurados.
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger
