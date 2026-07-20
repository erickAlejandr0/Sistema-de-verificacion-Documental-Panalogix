"""Vistas de lectura compuestas para la API REST."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.models.documento import Documento
from app.models.historial import Historial


class DocumentoConUltimoHistorial(BaseModel):
    """Documento con su extracción más reciente (si existe)."""

    model_config = ConfigDict(from_attributes=True)

    documento: Documento
    historial: Historial | None = None
