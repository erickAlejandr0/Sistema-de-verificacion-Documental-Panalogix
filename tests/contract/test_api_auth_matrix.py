"""Contrato: matriz de autorización de API keys (P6.1)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from app.handlers import api_handler
from tests.conftest import make_api_event


@pytest.fixture
def _api_keys(api_env: None) -> tuple[str, str]:
    from app.config import get_api_settings

    get_api_settings.cache_clear()
    s = get_api_settings()
    return s.panalogix_api_key, s.retool_api_key


@pytest.mark.contract
def test_missing_or_invalid_api_key_returns_401(_api_keys: tuple[str, str]) -> None:
    r1 = api_handler.handler(
        make_api_event("GET", "/verificaciones/pendientes"),
        None,
    )
    assert r1["statusCode"] == 401

    r2 = api_handler.handler(
        make_api_event(
            "GET",
            "/verificaciones/pendientes",
            api_key="totally-wrong-key-xxxxxx",
        ),
        None,
    )
    assert r2["statusCode"] == 401


@pytest.mark.contract
def test_retool_key_forbidden_on_ingestion_endpoints(
    _api_keys: tuple[str, str],
) -> None:
    _, retool = _api_keys
    for method, path, body in (
        ("POST", "/verificaciones", {"transportista_id": "x"}),
        ("POST", "/verificaciones/generar-url", {"content_type": "image/jpeg"}),
    ):
        resp = api_handler.handler(
            make_api_event(method, path, api_key=retool, body=body),
            None,
        )
        assert resp["statusCode"] == 403, path


@pytest.mark.contract
def test_panalogix_key_forbidden_on_retool_endpoints(
    _api_keys: tuple[str, str],
) -> None:
    panalogix, _ = _api_keys
    for method, path in (
        ("GET", "/verificaciones/pendientes"),
        (
            "POST",
            "/verificaciones/11111111-1111-1111-1111-111111111111/resolver",
        ),
    ):
        resp = api_handler.handler(
            make_api_event(method, path, api_key=panalogix, body={}),
            None,
        )
        assert resp["statusCode"] == 403, path


@pytest.mark.contract
def test_panalogix_can_reach_generar_url_past_authz(
    _api_keys: tuple[str, str],
) -> None:
    """AuthZ OK; el 422/200 posterior depende del mock — aquí solo no-403."""
    panalogix, _ = _api_keys
    pipeline = MagicMock()
    pipeline.generar_url.return_value = {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({"s3_key": "uploads/x.jpg"}),
    }
    with patch.object(api_handler, "ApiPipeline", return_value=pipeline):
        resp = api_handler.handler(
            make_api_event(
                "POST",
                "/verificaciones/generar-url",
                api_key=panalogix,
                body={"content_type": "image/jpeg"},
            ),
            None,
        )
    assert resp["statusCode"] == 200
    pipeline.generar_url.assert_called_once()
