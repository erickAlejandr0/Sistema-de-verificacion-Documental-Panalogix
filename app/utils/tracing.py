"""Bootstrap de instrumentación AWS X-Ray (idempotente, sin I/O).

``patch_all()`` cubre botocore/boto3, psycopg2 y httpx (Anthropic).
``httplib`` no entra en ``patch_all`` por defecto (está fuera de
``NO_DOUBLE_PATCH``); solo el webhook lo activa vía ``patch_httplib=True``
para instrumentar ``urllib.request``.

El patch de psycopg2 **no** escribe SQL ni parámetros bound en el
subsegmento — solo metadata de conexión (verificado en
``aws_xray_sdk.ext.dbapi2`` / ``ext.psycopg2.patch``).
"""

from __future__ import annotations

from app.utils.logging import get_logger

logger = get_logger(__name__)

_configured: bool = False
_httplib_patched: bool = False


def configure_xray(*, patch_httplib: bool = False) -> None:
    """Inicializa el SDK X-Ray una vez por proceso Lambda.

    Args:
        patch_httplib: Si ``True``, parchea también ``httplib`` (urllib).
            Usar solo en el handler webhook.
    """
    global _configured, _httplib_patched

    try:
        from aws_xray_sdk.core import patch, patch_all
    except ImportError:
        logger.warning(
            "xray_sdk_unavailable",
            extra={"patch_httplib": patch_httplib},
        )
        return

    if not _configured:
        patch_all()
        _configured = True
        logger.info("xray_configured", extra={"patch_httplib": False})

    if patch_httplib and not _httplib_patched:
        patch(("httplib",), raise_errors=False)
        _httplib_patched = True
        logger.info("xray_httplib_patched")


def _reset_for_tests() -> None:
    """Reinicia flags de módulo (solo tests unitarios)."""
    global _configured, _httplib_patched
    _configured = False
    _httplib_patched = False


def is_configured() -> bool:
    """Indica si ``patch_all`` ya corrió en este proceso."""
    return _configured


def is_httplib_patched() -> bool:
    """Indica si ``httplib`` ya fue parcheado en este proceso."""
    return _httplib_patched
