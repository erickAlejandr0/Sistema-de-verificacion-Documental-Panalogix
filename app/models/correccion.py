"""DTOs Pydantic de la entidad correcciones."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CorreccionCreate(BaseModel):
    """Datos para registrar una corrección humana sobre una extracción."""

    model_config = ConfigDict(str_strip_whitespace=True)

    historial_id: UUID
    campo_corregido: str = Field(..., max_length=60)
    valor_modelo: str | None = None
    valor_correcto: str = Field(..., min_length=1)
    # Identificador de usuario Retool (texto, p. ej. email), inyectado desde
    # la sesión autenticada de Retool como campo NO editable del formulario —
    # no un UUID relacional, no texto libre digitado por el revisor.
    # El SVD confía en el body sin validarlo contra identidad propia
    # (sin login/JWT en el SVD): decisión de costo-beneficio del MVP.
    corregido_por: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Identificador Retool del revisor (p. ej. email de sesión).",
    )


class Correccion(BaseModel):
    """Corrección persistida (lectura)."""

    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)

    id: UUID
    historial_id: UUID
    campo_corregido: str = Field(..., max_length=60)
    valor_modelo: str | None = None
    valor_correcto: str
    corregido_por: str = Field(..., max_length=255)
    corregido_en: datetime
