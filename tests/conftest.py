"""Fixtures compartidas — sin AWS/Anthropic/RDS reales."""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from app.config import (
    get_api_settings,
    get_common_settings,
    get_webhook_settings,
    get_worker_settings,
)
from app.models.documento import Documento
from app.models.enums import ResultadoVerificacion
from app.models.fields import CampoExtraido
from app.models.historial import Historial
from app.models.job import VerificationJobMessage
from app.services.ocr import ExtractionResult
from app.services.rules_engine import RulesEvaluation
from app.services.scoring import ScoringResult


@pytest.fixture(autouse=True)
def _clear_settings_caches() -> None:
    """Evita fuga de singletons lru_cache entre tests."""
    get_common_settings.cache_clear()
    get_worker_settings.cache_clear()
    get_api_settings.cache_clear()
    get_webhook_settings.cache_clear()
    yield
    get_common_settings.cache_clear()
    get_worker_settings.cache_clear()
    get_api_settings.cache_clear()
    get_webhook_settings.cache_clear()


def _wipe_settings_env() -> None:
    """Elimina variables de settings del proceso."""
    prefixes = (
        "AWS_",
        "DATABASE",
        "KMS_",
        "ENVIRONMENT",
        "ANTHROPIC",
        "MODELO",
        "UMBRAL",
        "AUTH_",
        "MAX_",
        "VERSION_",
        "PANALOGIX",
        "RETOOL",
        "WEBHOOK_",
    )
    for key in list(os.environ):
        if key.startswith(prefixes) or key in {"DATABASE_URL", "KMS_KEY_ID", "ENVIRONMENT"}:
            os.environ.pop(key, None)


@pytest.fixture
def common_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Solo variables de CommonSettings."""
    _wipe_settings_env()
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("AWS_SNS_TOPIC_ARN", "arn:aws:sns:us-east-1:123:svd-results")
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:5432/db")
    monkeypatch.setenv("KMS_KEY_ID", "alias/panalogix-pii")
    monkeypatch.setenv("ENVIRONMENT", "dev")


@pytest.fixture
def worker_env(common_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """Common + Worker (incluye Anthropic)."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-real")
    monkeypatch.setenv("AWS_S3_RAW_BUCKET", "svd-raw")
    monkeypatch.setenv("AWS_S3_VERIFIED_BUCKET", "svd-verified")
    monkeypatch.setenv("AWS_SQS_QUEUE_URL", "https://sqs.us-east-1.amazonaws.com/123/q")
    monkeypatch.setenv("MODELO_PRIMARIO", "claude-haiku-test")
    monkeypatch.setenv("MODELO_FALLBACK", "claude-sonnet-test")
    monkeypatch.setenv("UMBRAL_CONFIANZA", "0.92")
    monkeypatch.setenv("UMBRAL_AUTENTICIDAD", "0.70")
    monkeypatch.setenv("VERSION_EXTRACCION", "1.0.0")


@pytest.fixture
def api_env(common_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """Common + ApiSettings (sin Anthropic)."""
    monkeypatch.setenv("PANALOGIX_API_KEY", "key-panalogix-aaaaaaaa")
    monkeypatch.setenv("RETOOL_API_KEY", "key-retool-bbbbbbbbbb")
    monkeypatch.setenv("AWS_S3_RAW_BUCKET", "svd-raw")
    monkeypatch.setenv("AWS_SQS_QUEUE_URL", "https://sqs.us-east-1.amazonaws.com/123/q")


@pytest.fixture
def webhook_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Solo WebhookSettings (aislado)."""
    _wipe_settings_env()
    monkeypatch.setenv("WEBHOOK_URL", "https://receptor.example.com/hooks/svd")
    monkeypatch.setenv(
        "WEBHOOK_HMAC_SECRET",
        "example-webhook-secret-do-not-use-in-prod",
    )


@pytest.fixture
def documento_id() -> UUID:
    return uuid4()


@pytest.fixture
def transportista_id() -> UUID:
    return uuid4()


@pytest.fixture
def sample_documento(documento_id: UUID, transportista_id: UUID) -> Documento:
    return Documento(
        id=documento_id,
        transportista_id=transportista_id,
        tipo_documento="cedula",
        s3_key_raw="uploads/doc.jpg",
        s3_key_verified=None,
        subido_en=datetime.now(timezone.utc),
        eliminar_despues=date(2026, 12, 1),
    )


@pytest.fixture
def sample_job(documento_id: UUID) -> VerificationJobMessage:
    return VerificationJobMessage(
        documento_id=documento_id,
        cedula_registrada="8-123-456",
        placa_registrada="AB1234",
        nombre_registrado="Juan Perez",
        tipo_declarado="cedula",
    )


@pytest.fixture
def sample_historial(documento_id: UUID) -> Historial:
    return Historial(
        id=uuid4(),
        documento_id=documento_id,
        tipo_detectado="cedula",
        campos_extraidos={},
        campos_cifrados=None,
        resultado=ResultadoVerificacion.APROBADO,
        score_lectura=Decimal("0.950"),
        score_autenticidad=Decimal("0.900"),
        modelo_usado="claude-haiku-test",
        version_extraccion="1.0.0",
        prompt_hash="a" * 64,
        costo_api=Decimal("0.001000"),
        fecha_vencimiento=date(2027, 6, 15),
        procesado_en=datetime.now(timezone.utc),
    )


@pytest.fixture
def sample_extraction() -> ExtractionResult:
    return ExtractionResult(
        campos={
            "nombre": CampoExtraido(valor="Juan Perez", confianza=Decimal("0.990")),
            "placa": CampoExtraido(valor="AB1234", confianza=Decimal("0.980")),
        },
        tipo_detectado="cedula",
        modelo_usado="claude-haiku-test",
        costo_api=Decimal("0.001000"),
        anomalias=[],
        prompt_hash="a" * 64,
        confianza_minima=Decimal("0.980"),
    )


@pytest.fixture
def sample_rules() -> RulesEvaluation:
    return RulesEvaluation(has_reject=False, has_manual=False)


@pytest.fixture
def sample_scoring() -> ScoringResult:
    return ScoringResult(
        score_lectura=Decimal("0.950"),
        score_autenticidad=Decimal("0.900"),
        resultado=ResultadoVerificacion.APROBADO,
    )


def make_sqs_event(job: VerificationJobMessage) -> dict:
    """Envelope SQS mínimo para ``lambda_handler.handler``."""
    return {
        "Records": [
            {
                "messageId": "msg-1",
                "body": json.dumps(job.model_dump(mode="json")),
            }
        ]
    }


def make_api_event(
    method: str,
    path: str,
    *,
    api_key: str | None = None,
    body: dict | None = None,
    query: dict | None = None,
) -> dict:
    """Evento API Gateway REST v1 mínimo."""
    headers = {}
    if api_key is not None:
        headers["X-SVD-Api-Key"] = api_key
    return {
        "httpMethod": method,
        "path": path,
        "headers": headers,
        "body": None if body is None else json.dumps(body),
        "queryStringParameters": query,
        "isBase64Encoded": False,
    }


# Vector HMAC documentado en docs/contrato-webhook-panalogix.md
WEBHOOK_CONTRACT_BODY = (
    b'{"transportista_id":"11111111-1111-1111-1111-111111111111",'
    b'"tipo_documento":"cedula","resultado":"APROBADO",'
    b'"score_lectura":"0.955","score_autenticidad":"0.850",'
    b'"fecha_vencimiento":"2027-06-15"}'
)
WEBHOOK_CONTRACT_SECRET = "example-webhook-secret-do-not-use-in-prod"
WEBHOOK_CONTRACT_SIGNATURE = (
    "sha256=493f91ad97202c2b8282daba96607bbfe0da011b424bb8c4dc0d4b2e9d3b1ec0"
)
