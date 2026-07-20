"""DTOs Pydantic de la entidad patrones."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.fields import ScoreDecimal, empty_json_object


class PatronCreate(BaseModel):
    """Datos para registrar un patrón aprendido por tipo/variante."""

    model_config = ConfigDict(str_strip_whitespace=True)

    tipo_codigo: str = Field(..., max_length=40)
    subtipo: str = Field(
        default="",
        max_length=60,
        description="Variante; '' = sin subtipo (centinela, nunca NULL).",
    )
    estructura_detectada: dict[str, Any] = Field(default_factory=empty_json_object)
    confianza_promedio: ScoreDecimal | None = None
    muestras: int = Field(default=0, ge=0)


class Patron(BaseModel):
    """Patrón persistido (lectura)."""

    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)

    id: UUID
    tipo_codigo: str = Field(..., max_length=40)
    subtipo: str = Field(default="", max_length=60)
    estructura_detectada: dict[str, Any] = Field(default_factory=empty_json_object)
    confianza_promedio: ScoreDecimal | None = None
    muestras: int = Field(default=0, ge=0)
    actualizado_en: datetime
