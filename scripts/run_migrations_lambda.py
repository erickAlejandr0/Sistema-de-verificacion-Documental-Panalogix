"""Lambda desechable: aplica migrations/*.up.sql contra RDS (schema verificaciones).

Uso: invocar una vez tras el primer deploy del stack; luego borrar la función
y este archivo. No forma parte del pipeline de producción.

Empaquetado esperado (zip):
    run_migrations_lambda.py
    migrations/*.up.sql
    psycopg2/   # pip install -t

Handler: run_migrations_lambda.handler
"""

from __future__ import annotations

import json
import os
import traceback
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import psycopg2
from psycopg2 import errorcodes

# Empaquetar con migrations/ al lado de este .py.
_MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

# Errores de "objeto ya existe" → reintento idempotente.
_ALREADY_EXISTS = frozenset(
    {
        errorcodes.DUPLICATE_SCHEMA,  # 42P06
        errorcodes.DUPLICATE_TABLE,  # 42P07
        errorcodes.DUPLICATE_OBJECT,  # 42710
        errorcodes.DUPLICATE_COLUMN,  # 42701
    }
)


def _parse_database_url(database_url: str) -> dict[str, Any]:
    """Convierte DATABASE_URL en kwargs de psycopg2.connect.

    Args:
        database_url: URL estilo ``postgresql://user:pass@host:port/db``.

    Returns:
        Diccionario con host, port, user, password, dbname, connect_timeout.
    """
    parsed = urlparse(database_url)
    if not parsed.scheme.startswith("postgres"):
        raise ValueError(
            f"DATABASE_URL debe ser postgresql://, recibido: {parsed.scheme!r}"
        )
    return {
        "host": parsed.hostname or "localhost",
        "port": parsed.port or 5432,
        "user": unquote(parsed.username) if parsed.username else None,
        "password": unquote(parsed.password) if parsed.password else None,
        "dbname": (parsed.path or "/").lstrip("/") or None,
        "connect_timeout": 30,
    }


def _list_up_migrations(migrations_dir: Path) -> list[Path]:
    """Lista *.up.sql en orden numérico ascendente (001, 002, ...).

    Args:
        migrations_dir: Directorio con los scripts SQL.

    Returns:
        Paths ordenados por nombre.

    Raises:
        FileNotFoundError: Si no hay ningún ``*.up.sql``.
    """
    files = sorted(migrations_dir.glob("*.up.sql"))
    if not files:
        raise FileNotFoundError(
            f"No se encontraron *.up.sql en {migrations_dir}"
        )
    return files


def _apply_file(conn: Any, path: Path) -> str:
    """Ejecuta un .sql. Retorna ``applied`` o ``already_existed``.

    Args:
        conn: Conexión psycopg2 abierta.
        path: Archivo ``*.up.sql`` a ejecutar.

    Returns:
        ``"applied"`` si se ejecutó OK, ``"already_existed"`` si el objeto
        ya existía (reintento idempotente).

    Raises:
        Exception: Cualquier error que no sea de objeto ya existente.
    """
    sql = path.read_text(encoding="utf-8")
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()
        return "applied"
    except psycopg2.Error as exc:
        conn.rollback()
        pgcode = getattr(exc, "pgcode", None)
        if pgcode in _ALREADY_EXISTS:
            return "already_existed"
        raise


def handler(event: dict[str, Any], context: object) -> dict[str, Any]:
    """Aplica migrations 001–004 (*.up.sql) contra DATABASE_URL.

    Args:
        event: Evento Lambda (ignorado; invocar con ``{}``).
        context: Contexto Lambda (ignorado).

    Returns:
        Dict con ``statusCode`` y ``body`` JSON (aplicadas / ya existentes /
        error). Si un archivo falla, se detiene y reporta cuál.
    """
    del event, context

    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        body = {
            "ok": False,
            "error": "DATABASE_URL no está definida en el entorno",
            "applied": [],
            "already_existed": [],
            "failed": None,
        }
        return {"statusCode": 500, "body": json.dumps(body, ensure_ascii=False)}

    applied: list[str] = []
    already_existed: list[str] = []
    failed: str | None = None
    error_detail: str | None = None

    try:
        migrations = _list_up_migrations(_MIGRATIONS_DIR)
        conn = psycopg2.connect(**_parse_database_url(database_url))
        try:
            for path in migrations:
                name = path.name
                try:
                    status = _apply_file(conn, path)
                except Exception as exc:
                    failed = name
                    error_detail = f"{type(exc).__name__}: {exc}"
                    break
                if status == "applied":
                    applied.append(name)
                else:
                    already_existed.append(name)
        finally:
            conn.close()
    except Exception as exc:
        failed = failed or "(conexión / listado)"
        error_detail = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"

    ok = failed is None
    body = {
        "ok": ok,
        "migrations_dir": str(_MIGRATIONS_DIR),
        "applied": applied,
        "already_existed": already_existed,
        "failed": failed,
        "error": error_detail,
    }
    return {
        "statusCode": 200 if ok else 500,
        "body": json.dumps(body, ensure_ascii=False),
    }
