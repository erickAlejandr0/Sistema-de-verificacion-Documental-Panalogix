"""DTOs Pydantic de la entidad documentos."""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DocumentoCreate(BaseModel):
    """Datos para registrar un documento físico subido."""

    model_config = ConfigDict(str_strip_whitespace=True)

    transportista_id: UUID = Field(..., description="ID del transportista en Panalogix.")
    tipo_documento: str = Field(..., max_length=40, description="Tipo declarado al subir.")
    s3_key_raw: str = Field(..., min_length=1, description="Clave S3 en raw-docs.")
    s3_key_verified: str | None = Field(
        default=None,
        description="Clave S3 en verified-docs (solo si aprobado).",
    )


class Documento(BaseModel):
    """Documento físico persistido (lectura)."""

    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)

    id: UUID
    transportista_id: UUID
    tipo_documento: str = Field(..., max_length=40)
    s3_key_raw: str
    s3_key_verified: str | None = None
    subido_en: datetime
    eliminar_despues: date
