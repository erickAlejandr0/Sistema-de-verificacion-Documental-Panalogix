"""DTOs Pydantic de la entidad tipos_documento."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.fields import empty_json_object


class TipoDocumentoCreate(BaseModel):
    """Datos para registrar un tipo de documento en el catálogo."""

    model_config = ConfigDict(str_strip_whitespace=True)

    codigo: str = Field(..., max_length=40)
    nombre: str = Field(..., max_length=100)
    reglas_validacion: dict[str, Any] = Field(default_factory=empty_json_object)
    obligatorio: bool = True


class TipoDocumento(BaseModel):
    """Tipo de documento del catálogo (lectura)."""

    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)

    codigo: str = Field(..., max_length=40)
    nombre: str = Field(..., max_length=100)
    reglas_validacion: dict[str, Any] = Field(default_factory=empty_json_object)
    obligatorio: bool = True
