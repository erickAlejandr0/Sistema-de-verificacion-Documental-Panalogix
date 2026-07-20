"""DTOs del job de verificación (cola SQS) y requests de ingesta API."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class VerificationJobMessage(BaseModel):
    """Mensaje SQS con contexto de validación inyectado por Panalogix."""

    model_config = ConfigDict(str_strip_whitespace=True)

    documento_id: UUID
    cedula_registrada: str | None = None
    placa_registrada: str | None = None
    nombre_registrado: str | None = None
    tipo_declarado: str | None = Field(default=None, max_length=40)


class CrearVerificacionRequest(BaseModel):
    """Body de POST /verificaciones: documento + contexto para el job SQS."""

    model_config = ConfigDict(str_strip_whitespace=True)

    transportista_id: UUID
    tipo_documento: str = Field(..., max_length=40)
    s3_key_raw: str = Field(..., min_length=1)
    cedula_registrada: str | None = None
    placa_registrada: str | None = None
    nombre_registrado: str | None = None
    tipo_declarado: str | None = Field(default=None, max_length=40)


class CampoCorreccionItem(BaseModel):
    """Ítem opcional de corrección de campo en POST .../resolver."""

    model_config = ConfigDict(str_strip_whitespace=True)

    campo_corregido: str = Field(..., max_length=60)
    valor_modelo: str | None = None
    valor_correcto: str = Field(..., min_length=1)


class ResolverVerificacionRequest(BaseModel):
    """Body de POST /verificaciones/{id}/resolver.

    ``correcciones`` puede ser vacía: solo se cambia el resultado.
    ``corregido_por`` (top-level) se aplica a cada corrección registrada.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    resultado: Literal["APROBADO", "RECHAZADO"]
    corregido_por: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Identificador Retool del revisor (p. ej. email de sesión).",
    )
    correcciones: list[CampoCorreccionItem] = Field(default_factory=list)


class GenerarUrlRequest(BaseModel):
    """Body de POST /verificaciones/generar-url."""

    model_config = ConfigDict(str_strip_whitespace=True)

    content_type: Literal["image/jpeg", "image/png", "application/pdf"]


class PendientesQuery(BaseModel):
    """Query params de GET /verificaciones/pendientes."""

    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)
