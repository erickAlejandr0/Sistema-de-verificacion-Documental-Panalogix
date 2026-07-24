"""Contrato: GET /admin/patrones (Retool / RF-22) — frontera de red."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.handlers import api_handler
from app.handlers.api_handler import ApiPipeline
from app.models.patron import Patron
from app.services.field_applicability import DEFAULT_CAMPOS_APLICABLES
from tests.conftest import make_api_event

_KNOWN_FIELD_LABELS: frozenset[str] = frozenset(
    label for labels in DEFAULT_CAMPOS_APLICABLES.values() for label in labels
)

# Valores que podrían parecer PII real si filtraran en campos_tipicos.
_SEEDED_REAL_LOOKING_VALUES: frozenset[str] = frozenset(
    {
        "8-123-456",
        "Juan Perez",
        "AB1234",
    }
)


@pytest.fixture
def _api_keys(api_env: None) -> tuple[str, str]:
    from app.config import get_api_settings

    get_api_settings.cache_clear()
    s = get_api_settings()
    return s.panalogix_api_key, s.retool_api_key


@pytest.mark.contract
def test_admin_patrones_response_shape_and_network_boundary(
    _api_keys: tuple[str, str],
) -> None:
    """Frontera de red: campos_tipicos = labels canónicos, no datos reales.

    Primera exposición de ``estructura_detectada`` hacia un consumidor
    externo (Retool). No basta con la garantía de escritura de RF-22.
    """
    _, retool = _api_keys
    seeded_pii_cedula = "8-123-456"
    seeded_pii_nombre = "Juan Perez"
    assert seeded_pii_cedula in _SEEDED_REAL_LOOKING_VALUES
    assert seeded_pii_nombre in _SEEDED_REAL_LOOKING_VALUES

    patron = Patron(
        id=uuid4(),
        tipo_codigo="licencia",
        subtipo="",
        estructura_detectada={
            "campos_tipicos": ["cedula", "nombre_titular", "categoria"],
            "emisor": "ATTT",
        },
        confianza_promedio=Decimal("0.920"),
        muestras=4,
        actualizado_en=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
    )
    # El fixture simula que la escritura ya filtró PII; el test de frontera
    # verifica que lo que sale por HTTP sigue siendo solo labels.
    assert seeded_pii_cedula not in str(patron.estructura_detectada)
    assert seeded_pii_nombre not in str(patron.estructura_detectada)

    repo = MagicMock()
    repo.listar_todos.return_value = [patron]
    pipeline = ApiPipeline(
        verificacion_repo=MagicMock(),
        patron_repo=repo,
        s3_repo=MagicMock(),
        sqs_repo=MagicMock(),
        notifications=MagicMock(),
    )

    with patch.object(api_handler, "ApiPipeline", return_value=pipeline):
        resp = api_handler.handler(
            make_api_event("GET", "/admin/patrones", api_key=retool),
            None,
        )

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert "items" in body
    assert len(body["items"]) == 1
    item = body["items"][0]

    assert set(item.keys()) == {
        "tipo_codigo",
        "muestras",
        "confianza_promedio",
        "estructura_detectada",
        "actualizado_en",
    }
    assert "id" not in item
    assert "subtipo" not in item
    assert item["tipo_codigo"] == "licencia"
    assert item["muestras"] == 4
    assert item["confianza_promedio"] == "0.920"

    tipicos = item["estructura_detectada"]["campos_tipicos"]
    assert isinstance(tipicos, list)
    assert tipicos
    for label in tipicos:
        assert isinstance(label, str)
        assert label in _KNOWN_FIELD_LABELS, f"label no canónico: {label!r}"
        assert label not in _SEEDED_REAL_LOOKING_VALUES
        assert label != seeded_pii_cedula
        assert label != seeded_pii_nombre

    # Ningún string del JSON de tipicos parece un valor PII sembrado.
    tipicos_blob = json.dumps(tipicos)
    for seeded in _SEEDED_REAL_LOOKING_VALUES:
        assert seeded not in tipicos_blob

    assert item["estructura_detectada"].get("emisor") == "ATTT"


@pytest.mark.contract
def test_admin_patrones_empty_list(_api_keys: tuple[str, str]) -> None:
    _, retool = _api_keys
    repo = MagicMock()
    repo.listar_todos.return_value = []
    pipeline = ApiPipeline(
        verificacion_repo=MagicMock(),
        patron_repo=repo,
        s3_repo=MagicMock(),
        sqs_repo=MagicMock(),
        notifications=MagicMock(),
    )
    with patch.object(api_handler, "ApiPipeline", return_value=pipeline):
        resp = api_handler.handler(
            make_api_event("GET", "/admin/patrones", api_key=retool),
            None,
        )
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"]) == {"items": []}
