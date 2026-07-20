"""DTOs de contrato externo para notificaciones SNS (Panalogix).

Separados de Historial/Documento/Alerta de persistencia: el orquestador
arma estos payloads; el servicio SNS solo publica el contrato estable.
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

ResultadoLiteral = Literal["APROBADO", "RECHAZADO", "REVISION_MANUAL"]

_QUANTIZE = Decimal("0.001")


def decimal_score_to_str(value: Decimal | None) -> str | None:
    """Convierte un score Decimal a string NUMERIC(4,3); nunca float.

    Args:
        value: Score en [0, 1] o ``None``.

    Returns:
        Cadena cuantizada a 3 decimales, o ``None`` si ``value`` es ``None``.
    """
    if value is None:
        return None
    quantized = Decimal(str(value)).quantize(_QUANTIZE, rounding=ROUND_HALF_UP)
    return str(quantized)


def _validate_score_string(value: str | None) -> str | None:
    """Valida y cuantiza un score string a NUMERIC(4,3)."""
    if value is None:
        return None
    try:
        parsed = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"score no numérico: {value!r}") from exc
    if not Decimal("0") <= parsed <= Decimal("1"):
        raise ValueError(f"score fuera de rango [0, 1]: {value!r}")
    return str(parsed.quantize(_QUANTIZE, rounding=ROUND_HALF_UP))


class ResultadoPublicacion(BaseModel):
    """Contrato externo de resultado de verificación hacia Panalogix.

    Scores ya como string (precisión NUMERIC(4,3)); ``resultado`` como
    valor string del Enum, no como objeto Enum.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    transportista_id: UUID = Field(
        ...,
        description="ID del transportista en Panalogix (sin FK local).",
    )
    tipo_documento: str = Field(..., min_length=1, max_length=40)
    resultado: ResultadoLiteral = Field(
        ...,
        description="APROBADO | RECHAZADO | REVISION_MANUAL",
    )
    score_lectura: str | None = Field(
        default=None,
        description="Score de lectura como string (p. ej. '0.955').",
    )
    score_autenticidad: str | None = Field(
        default=None,
        description="Score de autenticidad como string (p. ej. '0.850').",
    )
    fecha_vencimiento: date | None = None

    @field_validator("resultado", mode="before")
    @classmethod
    def coerce_resultado(cls, value: object) -> object:
        """Acepta Enum ResultadoVerificacion y normaliza a su valor string."""
        if hasattr(value, "value"):
            return getattr(value, "value")
        return value

    @field_validator("score_lectura", "score_autenticidad")
    @classmethod
    def validate_score_string(cls, value: str | None) -> str | None:
        """Valida que el score string sea un Decimal en [0, 1] a 3 decimales."""
        return _validate_score_string(value)


class AlertaPublicacion(ResultadoPublicacion):
    """Contrato externo de alerta (vencimiento / revisión manual).

    Mismos 6 campos que ``ResultadoPublicacion`` para correlacionar con la
    verificación. ``dias_aviso`` y ``event_type`` NO viven aquí: el
    orquestador los pasa como kwargs a ``publicar_alerta``.
    """
