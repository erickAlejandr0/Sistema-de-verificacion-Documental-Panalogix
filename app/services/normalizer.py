"""Normalizador semántico hacia el modelo conceptual Panalogix.

Homologa labels heterogéneos de la extracción OCR a conceptos canónicos
(cedula, placa, fecha_vencimiento, nombre_titular, categoria), sin IA ni
acceso a datos.

Decisión de diseño (camino A / P3.4):
    ``NormalizedField`` NO incluye ``confianza``. Este módulo solo mapea
    nombres. El Rules Engine / scoring recibe AMBOS:

    1. ``dict[str, CampoExtraido]`` de OCR (P3.1) — confianzas y
       ``score_lectura``.
    2. La salida de ``normalizar`` — conceptos canónicos y
       ``label_original`` para validación cruzada de valores.

    El puente es ``label_original``: debe ser la clave CRUDA del dict de
    entrada (antes de casefold/strip/acentos del matching), para indexar
    de vuelta en el dict OCR original.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.fields import CampoExtraido

# Conceptos canónicos del modelo Panalogix (MVP).
CANONICAL_CONCEPTS: tuple[str, ...] = (
    "cedula",
    "placa",
    "fecha_vencimiento",
    "nombre_titular",
    "categoria",
)

# Sinónimos por concepto (labels ya normalizados con ``_normalize_label``).
# Extensible: añadir variantes sin cambiar la API pública.
CONCEPT_SYNONYMS: dict[str, frozenset[str]] = {
    "cedula": frozenset(
        {
            "cedula",
            "id",
            "identidad",
            "numero_cedula",
            "nro_cedula",
            "num_cedula",
            "documento_identidad",
            "dpi",
        }
    ),
    "placa": frozenset(
        {
            "placa",
            "matricula",
            "plate",
            "numero_placa",
            "nro_placa",
            "num_placa",
            "license_plate",
        }
    ),
    "fecha_vencimiento": frozenset(
        {
            "fecha_vencimiento",
            "vencimiento",
            "vence",
            "expiry",
            "expiration",
            "expiration_date",
            "valido_hasta",
            "vigencia_hasta",
            "fecha_expiracion",
            "expira",
        }
    ),
    "nombre_titular": frozenset(
        {
            "nombre_titular",
            "nombre",
            "titular",
            "full_name",
            "nombre_completo",
            "asegurado",
            "propietario",
            "conductor",
        }
    ),
    "categoria": frozenset(
        {
            "categoria",
            "cat",
            "clase",
            "tipo_licencia",
            "clase_licencia",
            "categoria_licencia",
        }
    ),
}


class NormalizedField(BaseModel):
    """Campo homologado al concepto Panalogix (sin confianza; ver módulo)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    valor: str | int | float | bool | None = Field(
        ...,
        description="Valor extraído asociado al concepto canónico.",
    )
    label_original: str = Field(
        ...,
        description="Clave cruda del dict OCR de entrada (puente a CampoExtraido).",
    )


def _normalize_label(label: str) -> str:
    """Normaliza un label solo para matching de sinónimos.

    No usar el resultado como ``label_original``.
    """
    decomposed = unicodedata.normalize("NFKD", label)
    without_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    cleaned = without_marks.casefold().strip()
    for sep in (" ", "-", "."):
        cleaned = cleaned.replace(sep, "_")
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned.strip("_")


def _extract_valor(raw: CampoExtraido | Mapping[str, Any] | Any) -> Any:
    """Obtiene el valor de un CampoExtraido o mapping compatible."""
    if isinstance(raw, CampoExtraido):
        return raw.valor
    if isinstance(raw, Mapping):
        return raw.get("valor")
    return getattr(raw, "valor", None)


def _build_synonym_index(
    synonyms: Mapping[str, frozenset[str]],
) -> dict[str, str]:
    """Índice label_normalizado → concepto canónico."""
    index: dict[str, str] = {}
    for concept, labels in synonyms.items():
        index[_normalize_label(concept)] = concept
        for label in labels:
            index[_normalize_label(label)] = concept
    return index


class SemanticNormalizer:
    """Mapea campos extraídos a conceptos canónicos Panalogix.

    Args:
        synonyms: Diccionario concepto → sinónimos (opcional; default del módulo).
    """

    def __init__(
        self,
        synonyms: Mapping[str, frozenset[str]] | None = None,
    ) -> None:
        """Inicializa el índice de sinónimos."""
        self._synonyms = dict(synonyms) if synonyms is not None else dict(CONCEPT_SYNONYMS)
        self._concepts = tuple(self._synonyms.keys()) or CANONICAL_CONCEPTS
        self._index = _build_synonym_index(self._synonyms)

    def normalizar(
        self,
        campos_extraidos: Mapping[str, CampoExtraido | Mapping[str, Any] | Any],
    ) -> dict[str, NormalizedField | None]:
        """Homologa labels OCR al modelo conceptual común.

        Args:
            campos_extraidos: Dict label→campo de la extracción (P3.1).

        Returns:
            Dict con una entrada por concepto canónico. Si no hay match,
            el valor es ``None`` (no falla). ``label_original`` es la clave
            cruda del input cuando hay match.
        """
        # concept → (raw_label, valor, is_exact_canonical)
        best: dict[str, tuple[str, Any, bool]] = {}

        for raw_label, raw_field in campos_extraidos.items():
            normalized = _normalize_label(raw_label)
            concept = self._index.get(normalized)
            if concept is None:
                continue

            valor = _extract_valor(raw_field)
            is_exact = normalized == _normalize_label(concept)
            previous = best.get(concept)
            if previous is None:
                best[concept] = (raw_label, valor, is_exact)
                continue
            # Desempate: preferir match exacto del nombre canónico.
            if is_exact and not previous[2]:
                best[concept] = (raw_label, valor, is_exact)
            # Si no, conservar el primero visto (orden de iteración del input).

        result: dict[str, NormalizedField | None] = {}
        for concept in self._concepts:
            hit = best.get(concept)
            if hit is None:
                result[concept] = None
            else:
                raw_label, valor, _ = hit
                result[concept] = NormalizedField(
                    valor=valor,
                    label_original=raw_label,
                )
        return result


def normalizar(
    campos_extraidos: Mapping[str, CampoExtraido | Mapping[str, Any] | Any],
) -> dict[str, NormalizedField | None]:
    """Atajo: normaliza con la instancia default del módulo.

    Args:
        campos_extraidos: Campos de la extracción OCR.

    Returns:
        Conceptos canónicos → ``NormalizedField`` o ``None``.
    """
    return SemanticNormalizer().normalizar(campos_extraidos)
