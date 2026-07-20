"""Enums que reflejan los CHECK constraints del schema verificaciones."""

from enum import Enum, IntEnum


class ResultadoVerificacion(str, Enum):
    """Clasificación de una verificación documental."""

    APROBADO = "APROBADO"
    RECHAZADO = "RECHAZADO"
    REVISION_MANUAL = "REVISION_MANUAL"


class EstadoAlerta(str, Enum):
    """Estado de una alerta de vencimiento."""

    PENDIENTE = "PENDIENTE"
    ENVIADA = "ENVIADA"
    FALLIDA = "FALLIDA"
    ATENDIDA = "ATENDIDA"


class DiasAviso(IntEnum):
    """Umbrales de aviso de vencimiento (días).

    Valores enteros alineados a ``alertas.dias_aviso`` (CHECK 30|7|0).
    Con ``use_enum_values=True`` en el modelo, el atributo queda como ``int``.
    """

    THIRTY = 30
    SEVEN = 7
    ZERO = 0
