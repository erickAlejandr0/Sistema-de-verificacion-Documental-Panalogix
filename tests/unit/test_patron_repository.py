"""Tests unitarios del upsert SQL de PatronRepository (RF-22)."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch

from app.models.patron import PatronCreate
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
