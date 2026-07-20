"""DTOs Pydantic de la entidad alertas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import DiasAviso, EstadoAlerta


class AlertaCreate(BaseModel):
    """Datos para registrar una alerta de vencimiento.

    Con ``use_enum_values=True``, ``dias_aviso`` y ``estado`` se normalizan
    a ``int`` / ``str`` planos en la validación de entrada (apto para psycopg2).
    """

    model_config = ConfigDict(
        from_attributes=True,
        str_strip_whitespace=True,
        use_enum_values=True,
    )

    historial_id: UUID
    dias_aviso: DiasAviso
    estado: EstadoAlerta = EstadoAlerta.PENDIENTE
    enviada_en: datetime | None = None


class Alerta(BaseModel):
    """Alerta persistida (lectura)."""

    model_config = ConfigDict(
        from_attributes=True,
        str_strip_whitespace=True,
        use_enum_values=True,
    )

    id: UUID
    historial_id: UUID
    dias_aviso: DiasAviso
    estado: EstadoAlerta = EstadoAlerta.PENDIENTE
    enviada_en: datetime | None = None
