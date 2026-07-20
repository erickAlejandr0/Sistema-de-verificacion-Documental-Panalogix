"""Integración DB: promedio móvil de patrones (3 upserts, m pre-UPDATE)."""

from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from app.models.patron import PatronCreate
from app.repositories.db import close_pool, get_connection, init_pool
from app.repositories.patron import PatronRepository


def _database_url_from_env_file() -> str | None:
    """Lee solo DATABASE_URL del .env local sin contaminar os.environ."""
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.is_file():
        return None
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        if key.strip() != "DATABASE_URL":
            continue
        url = value.strip().strip("'").strip('"')
        return url or None
    return None


def _resolve_database_url() -> str | None:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        url = (_database_url_from_env_file() or "").strip()
    if not url or "://u:p@" in url:
        return None
    return url


def _postgres_ready() -> str | None:
    """Devuelve DATABASE_URL si Postgres acepta conexión; si no, None."""
    url = _resolve_database_url()
    if url is None:
        return None
    try:
        close_pool()
        init_pool(url, minconn=1, maxconn=2)
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        return url
    except Exception:
        close_pool()
        return None


@pytest.fixture(scope="module")
def patron_db_url() -> str:
    url = _postgres_ready()
    if url is None:
        pytest.skip("Postgres local no disponible (DATABASE_URL)")
    yield url
    close_pool()


@pytest.mark.integration
def test_patron_upsert_running_average_three_samples(patron_db_url: str) -> None:
    """Tres upserts: m es el valor ANTES de cada UPDATE.

    c = 0.900, 0.800, 0.700:
      1) INSERT → m=1, conf=0.900
      2) m_antes=1 → (0.900*1+0.800)/(1+1)=0.850; m=2
      3) m_antes=2 → (0.850*2+0.700)/(2+1)=0.800; m=3
    """
    del patron_db_url  # fixture garantiza pool listo
    subtipo = f"__pytest_rf22_{uuid4().hex[:12]}"
    repo = PatronRepository()
    scores = (
        Decimal("0.900"),
        Decimal("0.800"),
        Decimal("0.700"),
    )
    try:
        last = None
        for score in scores:
            last = repo.upsert(
                PatronCreate(
                    tipo_codigo="licencia",
                    subtipo=subtipo,
                    estructura_detectada={"campos_tipicos": ["cedula"]},
                    confianza_promedio=score,
                )
            )
        assert last is not None
        assert last.muestras == 3
        assert last.confianza_promedio == Decimal("0.800")
    finally:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM verificaciones.patrones
                    WHERE tipo_codigo = %s AND subtipo = %s
                    """,
                    ("licencia", subtipo),
                )
