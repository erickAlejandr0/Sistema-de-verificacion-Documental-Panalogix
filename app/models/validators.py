"""Validadores de formato para campos del dominio SVD."""

from __future__ import annotations

import re
from datetime import date, datetime

# Prefijos numéricos (provincia) o alfanuméricos (PE, E, N, AV, …) + segmentos.
_PANAMA_CEDULA_PATTERN = re.compile(
    r"^(?:"
    r"[1-9]|1[0-3]|"  # provincias 1–13
    r"PE|E|N|AV|PI|"  # variantes especiales frecuentes
    r"[A-Z]{1,3}"  # otros prefijos literales cortos
    r")"
    r"-\d{1,4}-\d{1,6}$",
    re.IGNORECASE,
)


def validate_panama_cedula(value: str) -> str:
    """Valida y normaliza una cédula panameña.

    Acepta variantes con prefijo de provincia numérico (``8-XXX-XXXX``) y
    literales (``PE-XXX-XXXX``, ``E-XXX-XXXX``, ``N-…``, ``AV-…``, etc.).

    Args:
        value: Cédula en claro.

    Returns:
        Cédula normalizada (mayúsculas, sin espacios).

    Raises:
        ValueError: Si el formato no es válido.
    """
    if value is None or not str(value).strip():
        raise ValueError("la cédula no puede estar vacía")

    normalized = str(value).strip().upper().replace(" ", "")
    if not _PANAMA_CEDULA_PATTERN.match(normalized):
        raise ValueError(
            "formato de cédula panameña inválido "
            f"(se esperaba p. ej. 8-123-456 o PE-12-3456): {value!r}"
        )
    return normalized


def ensure_expiry_not_before_reference(
    expiry: date | None,
    reference: date | datetime | None,
) -> date | None:
    """Valida coherencia básica entre vencimiento y fecha de referencia.

    No aplica reglas de negocio de rechazo (RN); solo coherencia de forma.

    Args:
        expiry: Fecha de vencimiento del documento.
        reference: Fecha o momento de procesamiento / subida.

    Returns:
        La misma ``expiry`` si es válida o ``None``.

    Raises:
        ValueError: Si el vencimiento es anterior a la fecha de referencia.
    """
    if expiry is None or reference is None:
        return expiry

    ref_date = reference.date() if isinstance(reference, datetime) else reference
    if expiry < ref_date:
        raise ValueError(
            f"fecha_vencimiento {expiry.isoformat()} es anterior a "
            f"la referencia {ref_date.isoformat()}"
        )
    return expiry
