"""Modelos y schemas Pydantic del dominio SVD (schema verificaciones)."""

from app.models.alerta import Alerta, AlertaCreate
from app.models.correccion import Correccion, CorreccionCreate
from app.models.documento import Documento, DocumentoCreate
from app.models.enums import DiasAviso, EstadoAlerta, ResultadoVerificacion
from app.models.fields import (
    CampoCifrado,
    CampoExtraido,
    PanamaCedula,
    PiiName,
    PlaintextPiiPayload,
    ScoreDecimal,
)
from app.models.historial import Historial, HistorialCreate
from app.models.job import (
    CampoCorreccionItem,
    CrearVerificacionRequest,
    GenerarUrlRequest,
    PendientesQuery,
    ResolverVerificacionRequest,
    VerificationJobMessage,
)
from app.models.notificacion import (
    AlertaPublicacion,
    ResultadoPublicacion,
    decimal_score_to_str,
)
from app.models.patron import Patron, PatronCreate
from app.models.tipo_documento import TipoDocumento, TipoDocumentoCreate
from app.models.views import DocumentoConUltimoHistorial

__all__ = [
    "Alerta",
    "AlertaCreate",
    "AlertaPublicacion",
    "CampoCifrado",
    "CampoCorreccionItem",
    "CampoExtraido",
    "Correccion",
    "CorreccionCreate",
    "CrearVerificacionRequest",
    "DiasAviso",
    "Documento",
    "DocumentoConUltimoHistorial",
    "DocumentoCreate",
    "EstadoAlerta",
    "GenerarUrlRequest",
    "Historial",
    "HistorialCreate",
    "PanamaCedula",
    "Patron",
    "PatronCreate",
    "PendientesQuery",
    "PiiName",
    "PlaintextPiiPayload",
    "ResolverVerificacionRequest",
    "ResultadoPublicacion",
    "ResultadoVerificacion",
    "ScoreDecimal",
    "TipoDocumento",
    "TipoDocumentoCreate",
    "VerificationJobMessage",
    "decimal_score_to_str",
]
