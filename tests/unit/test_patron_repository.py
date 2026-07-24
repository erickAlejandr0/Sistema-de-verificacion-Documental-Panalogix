"""Tests unitarios del upsert SQL de PatronRepository (RF-22)."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch

import psycopg2
import pytest

from app.models.patron import PatronCreate
from app.repositories.exceptions import RepositoryError
from app.repositories.patron import PatronRepository


def test_upsert_sql_increments_muestras_and_running_average() -> None:
    """El SQL debe incrementar muestras y aplicar promedio con m pre-UPDATE."""
    repo = PatronRepository()
    data = PatronCreate(
        tipo_codigo="licencia",
        subtipo="",
        estructura_detectada={"campos_tipicos": ["cedula"]},
        confianza_promedio=Decimal("0.900"),
        muestras=99,
    )
    fake_row = {
        "id": "11111111-1111-1111-1111-111111111111",
        "tipo_codigo": "licencia",
        "subtipo": "",
        "estructura_detectada": {"campos_tipicos": ["cedula"]},
        "confianza_promedio": Decimal("0.900"),
        "muestras": 1,
        "actualizado_en": "2026-01-01T00:00:00+00:00",
    }
    cursor = MagicMock()
    cursor.fetchone.return_value = fake_row
    cursor_cm = MagicMock()
    cursor_cm.__enter__.return_value = cursor
    cursor_cm.__exit__.return_value = False
    conn = MagicMock()
    conn.cursor.return_value = cursor_cm
    conn_cm = MagicMock()
    conn_cm.__enter__.return_value = conn
    conn_cm.__exit__.return_value = False

    with patch("app.repositories.patron.get_connection", return_value=conn_cm):
        result = repo.upsert(data)

    assert result.muestras == 1
    sql: str = cursor.execute.call_args.args[0]
    assert "muestras = verificaciones.patrones.muestras + 1" in sql
    assert "VALUES (%s, %s, %s, %s, 1)" in sql.replace("\n", " ")
    assert "EXCLUDED.confianza_promedio" in sql
    assert "/ (verificaciones.patrones.muestras + 1)" in sql
    # No sobrescribe muestras con EXCLUDED.
    assert "muestras = EXCLUDED.muestras" not in sql
    params = cursor.execute.call_args.args[1]
    assert params[0] == "licencia"
    assert params[3] == Decimal("0.900")
    assert len(params) == 4


def _mock_conn_with_cursor(cursor: MagicMock) -> MagicMock:
    cursor_cm = MagicMock()
    cursor_cm.__enter__.return_value = cursor
    cursor_cm.__exit__.return_value = False
    conn = MagicMock()
    conn.cursor.return_value = cursor_cm
    conn_cm = MagicMock()
    conn_cm.__enter__.return_value = conn
    conn_cm.__exit__.return_value = False
    return conn_cm


def test_listar_todos_sql_order_and_mapping() -> None:
    repo = PatronRepository()
    fake_rows = [
        {
            "id": "11111111-1111-1111-1111-111111111111",
            "tipo_codigo": "cedula",
            "subtipo": "",
            "estructura_detectada": {"campos_tipicos": ["cedula"]},
            "confianza_promedio": Decimal("0.910"),
            "muestras": 3,
            "actualizado_en": "2026-03-01T00:00:00+00:00",
        },
        {
            "id": "22222222-2222-2222-2222-222222222222",
            "tipo_codigo": "licencia",
            "subtipo": "",
            "estructura_detectada": {
                "campos_tipicos": ["cedula", "nombre_titular"],
                "emisor": "ATTT",
            },
            "confianza_promedio": Decimal("0.880"),
            "muestras": 5,
            "actualizado_en": "2026-02-01T00:00:00+00:00",
        },
    ]
    cursor = MagicMock()
    cursor.fetchall.return_value = fake_rows
    with patch(
        "app.repositories.patron.get_connection",
        return_value=_mock_conn_with_cursor(cursor),
    ):
        result = repo.listar_todos()

    sql: str = cursor.execute.call_args.args[0]
    assert "FROM verificaciones.patrones" in sql
    assert "WHERE" not in sql
    assert (
        "ORDER BY tipo_codigo ASC, actualizado_en DESC, subtipo ASC" in sql
    )
    # execute(sql) sin parámetros.
    assert len(cursor.execute.call_args.args) == 1
    assert len(result) == 2
    assert result[0].tipo_codigo == "cedula"
    assert result[1].muestras == 5
    assert result[1].estructura_detectada["emisor"] == "ATTT"


def test_listar_todos_raises_repository_error_on_psycopg2() -> None:
    repo = PatronRepository()
    cursor = MagicMock()
    cursor.execute.side_effect = psycopg2.OperationalError("boom")
    with patch(
        "app.repositories.patron.get_connection",
        return_value=_mock_conn_with_cursor(cursor),
    ):
        with pytest.raises(RepositoryError, match="listar patrones"):
            repo.listar_todos()
