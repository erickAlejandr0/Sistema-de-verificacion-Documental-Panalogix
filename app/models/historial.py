"""DTOs Pydantic de la entidad historial (extracciones)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import ResultadoVerificacion
from app.models.fields import CampoCifrado, CampoExtraido, ScoreDecimal, empty_json_object
from app.models.validators import ensure_expiry_not_before_reference

CostoApiDecimal = Annotated[
    Decimal,
    Field(max_digits=10, decimal_places=6),
]


class HistorialCreate(BaseModel):
    """Datos para registrar una extracción sobre un documento."""

    model_config = ConfigDict(
        str_strip_whitespace=True,
        use_enum_values=True,
    )

    documento_id: UUID
    # Referencia libre (no FK) a tipos_documento.codigo — schema-agnostic.
    tipo_detectado: str | None = Field(default=None, max_length=40)
    campos_extraidos: dict[str, CampoExtraido] = Field(default_factory=empty_json_object)
    campos_cifrados: dict[str, CampoCifrado] | None = None
    resultado: ResultadoVerificacion
    score_lectura: ScoreDecimal | None = None
    score_autenticidad: ScoreDecimal | None = None
    modelo_usado: str | None = Field(default=None, max_length=30)
    version_extraccion: str | None = Field(default=None, max_length=20)
    prompt_hash: str | None = Field(default=None, max_length=64)
    costo_api: CostoApiDecimal | None = None
    fecha_vencimiento: date | None = None
    procesado_en: datetime | None = None

    @model_validator(mode="after")
    def validate_fecha_coherente(self) -> HistorialCreate:
        """Valida que fecha_vencimiento no sea anterior a procesado_en."""
        ensure_expiry_not_before_reference(self.fecha_vencimiento, self.procesado_en)
        return self


class Historial(BaseModel):
    """Extracción persistida (lectura)."""

    model_config = ConfigDict(
        from_attributes=True,
        str_strip_whitespace=True,
        use_enum_values=True,
    )

    id: UUID
    documento_id: UUID
    tipo_detectado: str | None = Field(default=None, max_length=40)
    campos_extraidos: dict[str, CampoExtraido] = Field(default_factory=empty_json_object)
    campos_cifrados: dict[str, CampoCifrado] | None = None
    resultado: ResultadoVerificacion
    score_lectura: ScoreDecimal | None = None
    score_autenticidad: ScoreDecimal | None = None
    modelo_usado: str | None = Field(default=None, max_length=30)
    version_extraccion: str | None = Field(default=None, max_length=20)
    prompt_hash: str | None = Field(default=None, max_length=64)
    costo_api: CostoApiDecimal | None = None
    fecha_vencimiento: date | None = None
    procesado_en: datetime
