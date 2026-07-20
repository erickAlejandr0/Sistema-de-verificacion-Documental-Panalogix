"""Armado de DTOs de notificación SNS desde entidades de dominio."""

from __future__ import annotations

from app.models.documento import Documento
from app.models.enums import ResultadoVerificacion
from app.models.historial import Historial
from app.models.notificacion import ResultadoPublicacion, decimal_score_to_str


def resultado_to_str(resultado: ResultadoVerificacion | str) -> str:
    """Normaliza resultado a string de dominio."""
    if isinstance(resultado, ResultadoVerificacion):
        return resultado.value
    return str(resultado)


def tipo_documento_publicacion(documento: Documento, historial: Historial) -> str:
    """Prefiere tipo_detectado; cae a tipo declarado del documento."""
    detected = (historial.tipo_detectado or "").strip()
    return detected if detected else documento.tipo_documento


def to_resultado_publicacion(
    documento: Documento,
    historial: Historial,
) -> ResultadoPublicacion:
    """Arma el DTO de contrato SNS desde Documento + Historial."""
    return ResultadoPublicacion(
        transportista_id=documento.transportista_id,
        tipo_documento=tipo_documento_publicacion(documento, historial),
        resultado=resultado_to_str(historial.resultado),
        score_lectura=decimal_score_to_str(historial.score_lectura),
        score_autenticidad=decimal_score_to_str(historial.score_autenticidad),
        fecha_vencimiento=historial.fecha_vencimiento,
    )
