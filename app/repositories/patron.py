"""Repositorio de patrones aprendidos (schema verificaciones.patrones)."""

from __future__ import annotations

import json
from typing import Any

import psycopg2
from psycopg2.extras import Json, RealDictCursor

from app.models.patron import Patron, PatronCreate
from app.repositories.db import get_connection
from app.repositories.exceptions import RepositoryError
from app.utils.logging import get_logger

logger = get_logger(__name__)


def _jsonb(value: Any) -> Json:
    """Envuelve un valor Python para columna JSONB."""
    return Json(value, dumps=lambda obj: json.dumps(obj, default=str))


def _normalize_subtipo(subtipo: str | None) -> str:
    """Normaliza subtipo al centinela '' cuando no aplica."""
    if subtipo is None:
        return ""
    return subtipo


class PatronRepository:
    """Upsert y consulta de patrones por tipo/variante."""

    def upsert(self, data: PatronCreate) -> Patron:
        """Inserta o actualiza un patrón de forma atómica.

        Usa ``ON CONFLICT (tipo_codigo, subtipo)``. El subtipo vacío ``''``
        representa “sin variante” (nunca NULL).

        Agregados reales en conflicto:
            - ``muestras``: ``patrones.muestras + 1`` (valor **antes** del UPDATE
              como base; el denominador del promedio es ``m + 1``).
            - ``confianza_promedio``: promedio móvil ponderado
              ``(COALESCE(old,0)*m + nueva) / (m + 1)``.

        ``estructura_detectada`` se sobrescribe con ``EXCLUDED`` (snapshot de
        la muestra más reciente, **no** un agregado histórico). El aprendizaje
        longitudinal de campos vive en ``historial``.

        Args:
            data: Datos del patrón. ``confianza_promedio`` es la confianza de
                la muestra actual (p. ej. ``score_lectura``). ``muestras`` del
                DTO no controla el UPDATE (INSERT fija ``1``).

        Returns:
            Patrón persistido.
        """
        subtipo = _normalize_subtipo(data.subtipo)
        sql = """
            INSERT INTO verificaciones.patrones (
                tipo_codigo, subtipo, estructura_detectada,
                confianza_promedio, muestras
            )
            VALUES (%s, %s, %s, %s, 1)
            ON CONFLICT (tipo_codigo, subtipo) DO UPDATE SET
                estructura_detectada = EXCLUDED.estructura_detectada,
                confianza_promedio = (
                    (COALESCE(verificaciones.patrones.confianza_promedio, 0)
                       * verificaciones.patrones.muestras
                     + EXCLUDED.confianza_promedio)
                    / (verificaciones.patrones.muestras + 1)
                ),
                muestras = verificaciones.patrones.muestras + 1,
                actualizado_en = now()
            RETURNING
                id, tipo_codigo, subtipo, estructura_detectada,
                confianza_promedio, muestras, actualizado_en
        """
        params = (
            data.tipo_codigo,
            subtipo,
            _jsonb(data.estructura_detectada),
            data.confianza_promedio,
        )
        try:
            with get_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(sql, params)
                    row = cur.fetchone()
            return Patron.model_validate(dict(row))
        except psycopg2.Error as exc:
            logger.error(
                "patron_upsert_failed",
                extra={"context": {"error": type(exc).__name__}},
            )
            raise RepositoryError("no se pudo hacer upsert del patrón") from exc

    def obtener_por_tipo(self, tipo_codigo: str) -> list[Patron]:
        """Lista patrones de un tipo de documento.

        Args:
            tipo_codigo: Código en ``tipos_documento``.

        Returns:
            Lista de patrones.
        """
        sql = """
            SELECT
                id, tipo_codigo, subtipo, estructura_detectada,
                confianza_promedio, muestras, actualizado_en
            FROM verificaciones.patrones
            WHERE tipo_codigo = %s
            ORDER BY actualizado_en DESC
        """
        try:
            with get_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(sql, (tipo_codigo,))
                    rows = cur.fetchall()
            return [Patron.model_validate(dict(r)) for r in rows]
        except psycopg2.Error as exc:
            raise RepositoryError("no se pudieron listar patrones") from exc
