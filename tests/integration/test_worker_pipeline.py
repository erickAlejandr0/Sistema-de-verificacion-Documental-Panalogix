"""Integración: happy path del worker hasta persistencia + SNS (mocks)."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, PropertyMock
from uuid import UUID

import pytest

from app.handlers.lambda_handler import VerificationPipeline
from app.models.documento import Documento
from app.models.historial import Historial
from app.models.job import VerificationJobMessage
from app.services.ocr import ExtractionResult
from app.services.rules_engine import RulesEvaluation
from app.services.scoring import ScoringResult


@pytest.mark.integration
def test_process_job_persists_historial_and_publishes_sns(
    sample_documento: Documento,
    sample_job: VerificationJobMessage,
    sample_extraction: ExtractionResult,
    sample_rules: RulesEvaluation,
    sample_scoring: ScoringResult,
    sample_historial: Historial,
) -> None:
    """SQS job → OCR mock → INSERT historial → publicar_resultado SNS."""
    repo = MagicMock()
    repo.obtener_documento.return_value = sample_documento
    repo.obtener_extraccion_idempotente.return_value = None
    repo.obtener_reglas_validacion.return_value = {}
    repo.registrar_extraccion.return_value = sample_historial

    ocr = MagicMock()
    type(ocr).prompt_hash = PropertyMock(return_value="a" * 64)
    ocr.extract.return_value = sample_extraction

    s3 = MagicMock()
    s3.descargar_raw.return_value = b"fake-jpeg-bytes"

    rules = MagicMock()
    rules.evaluate.return_value = sample_rules

    scoring = MagicMock()
    scoring.evaluate.return_value = sample_scoring

    notifications = MagicMock()
    notifications.publicar_resultado.return_value = "sns-msg-1"

    pipeline = VerificationPipeline(
        verificacion_repo=repo,
        s3_repo=s3,
        ocr=ocr,
        rules_engine=rules,
        scoring=scoring,
        notifications=notifications,
        patron_repo=MagicMock(),
        extraction_version="1.0.0",
    )
    pipeline.process_job(sample_job)

    ocr.extract.assert_called_once()
    s3.descargar_raw.assert_called_once_with(sample_documento.s3_key_raw)
    repo.registrar_extraccion.assert_called_once()
    create = repo.registrar_extraccion.call_args.args[0]
    assert create.documento_id == sample_documento.id
    assert create.prompt_hash == "a" * 64
    assert create.version_extraccion == "1.0.0"
    assert create.score_lectura == Decimal("0.950")

    notifications.publicar_resultado.assert_called_once()
    payload = notifications.publicar_resultado.call_args.args[0]
    assert payload.transportista_id == sample_documento.transportista_id
    assert str(payload.resultado) in {"APROBADO", sample_historial.resultado}
