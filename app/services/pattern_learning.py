"""Acumulación de patrones aprendidos (RF-22).

Soft-fail: un error de persistencia no tumba el job de verificación.

``estructura_detectada.campos_tipicos`` / ``emisor`` no se convierten en
métricas CloudWatch (texto/estructura; consultar RDS / historial).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol

from app.models.fields import CampoExtraido
from app.models.patron import Patron, PatronCreate
from app.repositories.exceptions import RepositoryError
from app.services.field_applicability import DEFAULT_CAMPOS_APLICABLES
from app.utils.logging import get_logger
from app.utils.metrics import emit_count, emit_value

logger = get_logger(__name__)

# Códigos con fila en tipos_documento (migración 004). Excluye desconocido.
TIPOS_DOCUMENTO_FK: frozenset[str] = frozenset(
    codigo for codigo in DEFAULT_CAMPOS_APLICABLES if codigo != "desconocido"
)
_TIPO_DESCONOCIDO: str = "desconocido"
_TIPOS_CONOCIDOS: frozenset[str] = TIPOS_DOCUMENTO_FK | {_TIPO_DESCONOCIDO}


class SupportsPatronUpsert(Protocol):
    """Abstracción mínima del repositorio de patrones."""

    def upsert(self, data: PatronCreate) -> Patron:
        """Inserta o actualiza un patrón."""
        ...


def build_estructura_detectada(
    campos: dict[str, CampoExtraido],
    *,
    entidad_emisora: str | None = None,
) -> dict[str, object]:
    """Arma el snapshot MVP de estructura (solo nombres de campo, Ley 81).

    ``campos_tipicos`` incluye claves con ``valor is not None`` (campo
    efectivamente extraído). No filtra por ``campos_aplicables``.

    Args:
        campos: Extracción tipada (pre-split PII).
        entidad_emisora: Emisor detectado por OCR, si existe.

    Returns:
        Dict para ``estructura_detectada`` (sin valores PII).
    """
    tipicos = sorted(k for k, v in campos.items() if v.valor is not None)
    estructura: dict[str, object] = {"campos_tipicos": tipicos}
    if entidad_emisora is not None:
        emisor = entidad_emisora.strip()
        if emisor:
            estructura["emisor"] = emisor
    return estructura


def accumulate_pattern(
    *,
    patron_repo: SupportsPatronUpsert,
    tipo_detectado: str,
    campos: dict[str, CampoExtraido],
    score_lectura: Decimal,
    entidad_emisora: str | None = None,
    tipo_declarado: str | None = None,
) -> None:
    """Registra o actualiza un patrón tras una extracción genuinamente nueva.

    - Solo tipos del catálogo FK (6 códigos sembrados).
    - ``desconocido``: skip documentado (FK + RN-03) + métrica
      ``DocumentosTipoDesconocido``.
    - Tipo residual fuera de ``(6 ∪ {desconocido})``: skip con log distinto
      (señal de tipo no anticipado).
    - Soft-fail ante ``RepositoryError`` (RF-22 Could).
    - Tras upsert OK: ``PatronesActualizados`` + ``PatronesConfianzaPromedio``
      (valor = promedio móvil en BD, no un promedio de la métrica).

    ``estructura_detectada`` es snapshot de la muestra actual (overwrite en
    BD); ``muestras`` / ``confianza_promedio`` son los agregados reales.

    Args:
        patron_repo: Repositorio inyectable.
        tipo_detectado: Código detectado por OCR.
        campos: Campos de la extracción (pre-split).
        score_lectura: Confianza de lectura de esta muestra.
        entidad_emisora: Emisor opcional desde OCR.
        tipo_declarado: Declarado por Panalogix (dimensión métrica desconocido).
    """
    tipo = (tipo_detectado or "").strip().lower()

    if tipo == _TIPO_DESCONOCIDO:
        declarado = (tipo_declarado or "").strip() or "none"
        logger.info(
            "patron_skip_desconocido",
            extra={
                "context": {
                    "motivo": "fk_tipos_documento_y_rn03",
                    "tipo_detectado": tipo,
                }
            },
        )
        emit_count(
            "DocumentosTipoDesconocido",
            dimensions={"tipo_declarado": declarado[:40]},
        )
        return

    if tipo not in _TIPOS_CONOCIDOS:
        logger.warning(
            "patron_skip_tipo_fuera_catalogo",
            extra={
                "context": {
                    "motivo": "tipo_no_anticipado_fk",
                    "tipo_detectado": tipo,
                }
            },
        )
        return

    estructura = build_estructura_detectada(campos, entidad_emisora=entidad_emisora)
    payload = PatronCreate(
        tipo_codigo=tipo,
        subtipo="",
        estructura_detectada=estructura,
        confianza_promedio=score_lectura,
        muestras=1,
    )
    try:
        patron = patron_repo.upsert(payload)
    except RepositoryError as exc:
        logger.warning(
            "patron_accumulate_failed",
            extra={
                "context": {
                    "tipo_detectado": tipo,
                    "error": type(exc).__name__,
                }
            },
        )
        return

    dims = {"tipo_codigo": tipo}
    emit_count("PatronesActualizados", dimensions=dims)
    if patron.confianza_promedio is not None:
        emit_value(
            "PatronesConfianzaPromedio",
            float(patron.confianza_promedio),
            dimensions=dims,
        )
