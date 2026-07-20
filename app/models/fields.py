"""Modelos de apoyo para JSONB y tipado PII previo a cifrado KMS."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from app.models.validators import validate_panama_cedula

ScoreDecimal = Annotated[
    Decimal,
    Field(ge=0, le=1, max_digits=4, decimal_places=3),
]

PanamaCedula = Annotated[
    str,
    AfterValidator(validate_panama_cedula),
    Field(
        json_schema_extra={"pii": True, "encrypt": True, "pii_field": "cedula"},
        description="Cédula panameña en claro; debe cifrarse antes de persistir.",
    ),
]

PiiName = Annotated[
    str,
    Field(
        min_length=1,
        json_schema_extra={
            "pii": True,
            "encrypt": True,
            "pii_field": "nombre_titular",
        },
        description="Nombre del titular en claro; debe cifrarse antes de persistir.",
    ),
]


class CampoExtraido(BaseModel):
    """Campo no sensible extraído de un documento (``campos_extraidos``)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    valor: str | int | float | bool | None = Field(
        ...,
        description="Valor extraído no sensible.",
    )
    confianza: ScoreDecimal = Field(
        ...,
        description="Confianza de la extracción (0.000–1.000).",
    )


class CampoCifrado(BaseModel):
    """Campo PII cifrado con KMS (``campos_cifrados``)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    valor_cifrado: str = Field(
        ...,
        min_length=1,
        description="Ciphertext en base64 (nunca el dato en claro).",
    )
    confianza: ScoreDecimal = Field(
        ...,
        description="Confianza de la extracción del campo PII.",
    )


class PlaintextPiiPayload(BaseModel):
    """PII en claro previo al cifrado KMS (no se persiste así).

    Attributes:
        cedula: Cédula panameña marcada como PII.
        nombre_titular: Nombre completo marcado como PII.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    cedula: PanamaCedula
    nombre_titular: PiiName


def empty_json_object() -> dict[str, Any]:
    """Factory para defaults JSONB ``{}``."""
    return {}
