"""Pool de conexiones PostgreSQL (psycopg2) para el schema verificaciones."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from typing import Any
from urllib.parse import unquote, urlparse

from psycopg2.extensions import connection as PgConnection
from psycopg2.pool import ThreadedConnectionPool

from app.utils.logging import get_logger

logger = get_logger(__name__)

_pool: ThreadedConnectionPool | None = None


def _parse_database_url(database_url: str) -> dict[str, Any]:
    """Convierte DATABASE_URL en kwargs de ``psycopg2.connect``.

    Args:
        database_url: URL estilo ``postgresql://user:pass@host:port/db``.

    Returns:
        Diccionario con host, port, user, password, dbname.
    """
    parsed = urlparse(database_url)
    if not parsed.scheme.startswith("postgres"):
        raise ValueError(f"DATABASE_URL debe ser postgresql://, recibido: {parsed.scheme!r}")

    return {
        "host": parsed.hostname or "localhost",
        "port": parsed.port or 5432,
        "user": unquote(parsed.username) if parsed.username else None,
        "password": unquote(parsed.password) if parsed.password else None,
        "dbname": (parsed.path or "/").lstrip("/") or None,
    }


def init_pool(
    database_url: str | None = None,
    *,
    minconn: int = 1,
    maxconn: int = 10,
) -> ThreadedConnectionPool:
    """Inicializa (o reutiliza) el pool global de conexiones.

    Args:
        database_url: URL de RDS. Si es ``None``, se lee de settings.
        minconn: Conexiones mínimas del pool.
        maxconn: Conexiones máximas del pool.

    Returns:
        Instancia del pool.
    """
    global _pool
    if _pool is not None:
        return _pool

    if database_url is None:
        from app.config import get_common_settings

        database_url = get_common_settings().database_url

    connect_kwargs = _parse_database_url(database_url)
    _pool = ThreadedConnectionPool(minconn, maxconn, **connect_kwargs)
    logger.info(
        "db_pool_initialized",
        extra={"context": {"minconn": minconn, "maxconn": maxconn}},
    )
    return _pool


def close_pool() -> None:
    """Cierra todas las conexiones del pool global."""
    global _pool
    if _pool is not None:
        _pool.closeall()
        _pool = None
        logger.info("db_pool_closed", extra={"context": {}})


def get_pool() -> ThreadedConnectionPool:
    """Devuelve el pool, inicializándolo si hace falta.

    Returns:
        Pool activo.

    Raises:
        RuntimeError: Si el pool no pudo crearse.
    """
    if _pool is None:
        init_pool()
    if _pool is None:
        raise RuntimeError("no se pudo inicializar el pool de conexiones")
    return _pool


@contextmanager
def get_connection(*, autocommit: bool = False) -> Generator[PgConnection, None, None]:
    """Context manager: obtiene una conexión del pool y la libera.

    Hace ``commit`` al salir sin error y ``rollback`` si hay excepción,
    salvo que ``autocommit`` esté activo.

    Args:
        autocommit: Si es True, no gestiona commit/rollback.

    Yields:
        Conexión psycopg2.
    """
    pool = get_pool()
    conn = pool.getconn()
    try:
        if autocommit:
            conn.autocommit = True
        yield conn
        if not autocommit:
            conn.commit()
    except Exception:
        if not autocommit:
            conn.rollback()
        raise
    finally:
        conn.autocommit = False
        pool.putconn(conn)


def row_to_dict(cursor: Any, row: tuple[Any, ...] | None) -> dict[str, Any] | None:
    """Mapea una fila a dict usando los nombres de columna del cursor.

    Args:
        cursor: Cursor con ``description`` poblada.
        row: Tupla de valores o ``None``.

    Returns:
        Diccionario columna→valor, o ``None`` si ``row`` es ``None``.
    """
    if row is None:
        return None
    columns = [col.name for col in cursor.description]
    return dict(zip(columns, row, strict=True))


def rows_to_dicts(cursor: Any, rows: list[tuple[Any, ...]]) -> list[dict[str, Any]]:
    """Mapea varias filas a dicts.

    Args:
        cursor: Cursor con ``description`` poblada.
        rows: Lista de tuplas.

    Returns:
        Lista de diccionarios.
    """
    columns = [col.name for col in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in rows]
