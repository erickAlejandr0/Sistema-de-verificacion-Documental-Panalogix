"""Integración: aislamiento de Settings por punto de entrada.

Los tests construyen Settings con ``_env_file=None`` para no leer el
``.env`` del repo: solo cuentan variables del proceso (fixtures). Así el
resultado es determinista con o sin ``.env`` local.
"""

from __future__ import annotations

import os

import pytest
from pydantic import ValidationError

from app.config import (
    ApiSettings,
    CommonSettings,
    WebhookSettings,
    WorkerSettings,
)


@pytest.mark.integration
def test_common_settings_loads_without_anthropic(common_env: None) -> None:
    """Alerts/paths compartidos usan CommonSettings — sin ANTHROPIC_API_KEY."""
    assert "ANTHROPIC_API_KEY" not in os.environ
    settings = CommonSettings(_env_file=None)
    assert settings.environment == "dev"
    assert settings.aws_region == "us-east-1"
    assert not hasattr(settings, "anthropic_api_key")


@pytest.mark.integration
def test_api_settings_loads_without_anthropic(api_env: None) -> None:
    """ApiSettings no exige Anthropic ni umbrales OCR."""
    assert "ANTHROPIC_API_KEY" not in os.environ
    api = ApiSettings(_env_file=None)
    assert api.panalogix_api_key.startswith("key-panalogix")
    assert api.aws_s3_raw_bucket == "svd-raw"
    assert not hasattr(api, "anthropic_api_key")


@pytest.mark.integration
def test_webhook_settings_isolated_from_common(webhook_env: None) -> None:
    """WebhookSettings solo necesita URL + secreto HMAC."""
    assert "DATABASE_URL" not in os.environ
    assert "ANTHROPIC_API_KEY" not in os.environ
    wh = WebhookSettings(_env_file=None)
    assert wh.webhook_url.startswith("https://")
    assert not hasattr(wh, "database_url")


@pytest.mark.integration
def test_worker_settings_requires_anthropic(common_env: None) -> None:
    """WorkerSettings falla sin ANTHROPIC_API_KEY (y resto worker)."""
    assert "ANTHROPIC_API_KEY" not in os.environ
    with pytest.raises(ValidationError):
        WorkerSettings(_env_file=None)


@pytest.mark.integration
def test_worker_settings_loads_with_full_env(worker_env: None) -> None:
    """WorkerSettings instancia cuando el env worker está completo."""
    ws = WorkerSettings(_env_file=None)
    assert ws.anthropic_api_key.startswith("sk-test")
    assert ws.extraction_version == "1.0.0"
