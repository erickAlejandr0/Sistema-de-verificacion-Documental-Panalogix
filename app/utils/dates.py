"""Utilidades de fechas y vigencia documental.

Parseo en formato panameño (DD/MM/YYYY), cálculo de días hasta vencimiento
y zona horaria America/Panama.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

PANAMA_TZ: ZoneInfo = ZoneInfo("America/Panama")
_PANAMA_DATE_FORMAT: str = "%d/%m/%Y"


class InvalidDateFormatError(ValueError):
    """La fecha no cumple el formato panameño DD/MM/YYYY o es inválida."""


def parse_panama_date(value: str) -> date:
    """Parsea una fecha en formato DD/MM/YYYY.

    Args:
        value: Cadena con la fecha (p. ej. ``15/03/2026``).

    Returns:
        Objeto ``date`` correspondiente.

    Raises:
        InvalidDateFormatError: Si el formato es incorrecto o la fecha no existe.
    """
    if not value or not value.strip():
        raise InvalidDateFormatError("la fecha no puede estar vacía")

    try:
        return datetime.strptime(value.strip(), _PANAMA_DATE_FORMAT).date()
    except ValueError as exc:
        raise InvalidDateFormatError(
            f"fecha inválida o formato incorrecto (se espera DD/MM/YYYY): {value!r}"
        ) from exc


def format_panama_date(value: date) -> str:
    """Formatea una fecha al patrón panameño DD/MM/YYYY.

    Args:
        value: Fecha a formatear.

    Returns:
        Cadena en formato ``DD/MM/YYYY``.
    """
    return value.strftime(_PANAMA_DATE_FORMAT)


def days_until_expiry(expiry: date, *, today: date | None = None) -> int:
    """Calcula los días restantes hasta la fecha de vencimiento.

    Args:
        expiry: Fecha de vencimiento del documento.
        today: Día de referencia. Si es ``None``, usa la fecha actual en
            America/Panama.

    Returns:
        Días hasta el vencimiento. Negativo si ya venció; ``0`` si vence hoy.
    """
    reference = today if today is not None else datetime.now(PANAMA_TZ).date()
    return (expiry - reference).days
