"""Resolución de campos aplicables por tipo de documento.

``campos_aplicables`` vive en ``tipos_documento.reglas_validacion`` (JSONB)
y se combina con defaults en código (Open/Closed). Usado por OCR
(``confianza_minima``) y Scoring (``score_lectura``).

Vocabulario cerrado: la fuente de verdad de nombres de campo son los
prompts (P3.2) + ``campos_aplicables``. Los sinónimos aquí son solo red
de seguridad si el modelo se desvía del vocabulario cerrado.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any

from app.models.fields import CampoExtraido
from app.utils.logging import get_logger

logger = get_logger(__name__)

_ZERO = Decimal("0.000")

DEFAULT_CAMPOS_APLICABLES: dict[str, tuple[str, ...]] = {
    "licencia": (
        "cedula",
        "nombre_titular",
        "categoria",
        "fecha_emision",
        "fecha_vencimiento",
    ),
    "soat": (
        "placa",
        "aseguradora",
        "poliza",
        "fecha_emision",
        "fecha_vencimiento",
        "nombre_titular",
    ),
    "cedula": (
        "cedula",
        "nombre_titular",
        "fecha_nacimiento",
        "fecha_emision",
        "fecha_vencimiento",
    ),
    "revisado": (
        "placa",
        "resultado",
        "centro",
        "fecha_emision",
        "fecha_vencimiento",
    ),
    "crct": (
        "cedula",
        "nombre_titular",
        "numero_certificado",
        "fecha_emision",
        "fecha_vencimiento",
    ),
    "permiso_pesos": (
        "placa",
        "peso_maximo",
        "dimensiones",
        "fecha_emision",
        "fecha_vencimiento",
    ),
    "desconocido": (),
}

# Labels ya normalizados (casefold / sin acentos). Red de seguridad secundaria.
APPLICABLE_FIELD_SYNONYMS: dict[str, frozenset[str]] = {
    "poliza": frozenset({"poliza", "numero_poliza", "nro_poliza", "num_poliza"}),
    "centro": frozenset({"centro", "centro_autorizado", "centro_revision"}),
    "numero_certificado": frozenset(
        {"numero_certificado", "certificado", "nro_certificado", "num_certificado"}
    ),
    "peso_maximo": frozenset({"peso_maximo", "peso", "peso_max", "capacidad_peso"}),
    "resultado": frozenset({"resultado", "resultado_revisado", "dictamen"}),
    "aseguradora": frozenset(
        {"aseguradora", "empresa_aseguradora", "compania_aseguradora"}
    ),
}


def _normalize_label(label: str) -> str:
    """Normaliza un label para matching (sin acentos, casefold)."""
    decomposed = unicodedata.normalize("NFKD", label)
    without_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    cleaned = without_marks.casefold().strip()
    for sep in (" ", "-", "."):
        cleaned = cleaned.replace(sep, "_")
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned.strip("_")


def _aliases_for(canonical: str) -> frozenset[str]:
    """Canónico + sinónimos conocidos (normalizados)."""
    norm = _normalize_label(canonical)
    synonyms = APPLICABLE_FIELD_SYNONYMS.get(norm, frozenset())
    return frozenset({norm}) | synonyms


def resolve_campos_aplicables(
    tipo_detectado: str,
    reglas_validacion: Mapping[str, Any] | None = None,
) -> frozenset[str]:
    """Resuelve la lista canónica de campos aplicables al tipo.

    JSONB ``campos_aplicables`` gana sobre ``DEFAULT_CAMPOS_APLICABLES``.

    Decisión consciente — ``desconocido`` / lista vacía:
        Devuelve ``frozenset()``. El problema original (campos irrelevantes
        arrastrando ``confianza_minima`` / ``score_lectura``) **sigue sin
        resolverse** si el caller aplica el fallback de usar todas las
        claves presentes. Es aceptable porque RN-03 ya rechaza documentos
        de tipo desconocido; el score no cambia el outcome de
        clasificación. No es un caso olvidado.

    Args:
        tipo_detectado: Código de tipo (p. ej. ``licencia``).
        reglas_validacion: JSONB de ``tipos_documento`` (override opcional).

    Returns:
        Conjunto de labels canónicos aplicables (vacío si desconocido
        o sin default / override).
    """
    tipo = (tipo_detectado or "").casefold().strip()
    default = DEFAULT_CAMPOS_APLICABLES.get(tipo, ())
    resolved: Sequence[str] = default

    if reglas_validacion is not None:
        raw = reglas_validacion.get("campos_aplicables")
        if isinstance(raw, (list, tuple)) and raw:
            resolved = [str(item).strip() for item in raw if str(item).strip()]
        elif isinstance(raw, (list, tuple)) and not raw:
            # Override explícito vacío (p. ej. desconocido en JSONB).
            resolved = ()

    return frozenset(_normalize_label(name) for name in resolved if name)


def confidences_for_aplicables(
    campos: Mapping[str, CampoExtraido],
    aplicables: Sequence[str] | frozenset[str],
) -> list[Decimal]:
    """Confianzas OCR solo de campos aplicables (ausente → 0.000).

    Red de seguridad: acepta sinónimos conocidos (p. ej. ``numero_poliza``
    por ``poliza``). Si el canónico no aparece ni por sinónimo, emite
    ``log.warning`` (``campo_aplicable_ausente``) — el vocabulario cerrado
    de los prompts es la defensa principal.

    Args:
        campos: Extracción OCR (label → ``CampoExtraido``).
        aplicables: Labels canónicos aplicables. Si vacío, el caller debe
            haber aplicado antes el fallback de ``desconocido``.

    Returns:
        Lista de confianzas Decimal (una por label aplicable), en orden
        de ``aplicables`` si es secuencia; orden arbitrario si frozenset.
    """
    by_norm: dict[str, CampoExtraido] = {
        _normalize_label(key): campo for key, campo in campos.items()
    }
    result: list[Decimal] = []
    for name in aplicables:
        aliases = _aliases_for(name)
        campo: CampoExtraido | None = None
        for alias in aliases:
            found = by_norm.get(alias)
            if found is not None:
                campo = found
                break
        if campo is None:
            logger.warning(
                "campo_aplicable_ausente",
                extra={
                    "context": {
                        "campo_canonico": _normalize_label(name),
                        "aliases_buscados": sorted(aliases),
                    }
                },
            )
            result.append(_ZERO)
        else:
            result.append(Decimal(str(campo.confianza)))
    return result


def min_confidence_aplicables(
    campos: Mapping[str, CampoExtraido],
    aplicables: frozenset[str],
) -> Decimal:
    """Mínima confianza entre campos aplicables (fallback: todas las claves).

    Si ``aplicables`` está vacío (p. ej. ``desconocido``), usa todas las
    confianzas presentes — ver docstring de ``resolve_campos_aplicables``.
    """
    if not aplicables:
        if not campos:
            return _ZERO
        return min(
            (Decimal(str(c.confianza)) for c in campos.values()),
            default=_ZERO,
        )
    values = confidences_for_aplicables(campos, aplicables)
    if not values:
        return _ZERO
    return min(values)
