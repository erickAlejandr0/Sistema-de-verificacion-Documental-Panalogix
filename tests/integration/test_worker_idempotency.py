"""Integración: protocolo de idempotencia P4.2 (OCR/INSERT vs SNS always-on)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, PropertyMock
from uuid import uuid4

import pytest

from app.handlers.lambda_handler import VerificationPipeline
from app.models.alerta import Alerta
from app.models.documento import Documento
from app.models.enums import DiasAviso, EstadoAlerta, ResultadoVerificacion
from app.models.historial import Historial
from app.models.job import VerificationJobMessage
from app.services.ocr import ExtractionResult
from app.services.rules_engine import RulesEvaluation
from app.services.scoring import ScoringResult
from app.services.sns import RetryableNotificationError


def _pipeline(
    *,
    repo: MagicMock,
    ocr: MagicMock,
    notifications: MagicMock,
    s3: MagicMock | None = None,
    rules: MagicMock | None = None,
    scoring: MagicMock | None = None,
    patron_repo: MagicMock | None = None,
) -> VerificationPipeline:
    return VerificationPipeline(
        verificacion_repo=repo,
        s3_repo=s3 or MagicMock(),
        ocr=ocr,
        rules_engine=rules or MagicMock(),
        scoring=scoring or MagicMock(),
        notifications=notifications,
        patron_repo=patron_repo or MagicMock(),
        extraction_version="1.0.0",
    )


@pytest.mark.integration
def test_idempotent_hit_skips_ocr_and_insert_but_always_publishes_sns(
    sample_documento: Documento,
    sample_job: VerificationJobMessage,
    sample_historial: Historial,
    sample_extraction: ExtractionResult,
    sample_rules: RulesEvaluation,
    sample_scoring: ScoringResult,
) -> None:
    """Reproceso mismo documento+hash+version: sin Claude/INSERT; SNS sí."""
    repo = MagicMock()
    repo.obtener_documento.return_value = sample_documento
    # 1ª corrida: miss; 2ª: hit
    repo.obtener_extraccion_idempotente.side_effect = [None, sample_historial]
    repo.obtener_reglas_validacion.return_value = {}
    repo.registrar_extraccion.return_value = sample_historial

    ocr = MagicMock()
    type(ocr).prompt_hash = PropertyMock(return_value="a" * 64)
    ocr.extract.return_value = sample_extraction

    s3 = MagicMock()
    s3.descargar_raw.return_value = b"img"
    rules = MagicMock()
    rules.evaluate.return_value = sample_rules
    scoring = MagicMock()
    scoring.evaluate.return_value = sample_scoring
    notifications = MagicMock()
    notifications.publicar_resultado.return_value = "sns-1"
    patron_repo = MagicMock()

    pipeline = _pipeline(
        repo=repo,
        ocr=ocr,
        notifications=notifications,
        s3=s3,
        rules=rules,
        scoring=scoring,
        patron_repo=patron_repo,
    )

    pipeline.process_job(sample_job)
    assert ocr.extract.call_count == 1
    assert repo.registrar_extraccion.call_count == 1
    assert patron_repo.upsert.call_count == 1
    assert notifications.publicar_resultado.call_count == 1

    pipeline.process_job(sample_job)
    assert ocr.extract.call_count == 1  # no segunda extracción
    assert repo.registrar_extraccion.call_count == 1
    assert patron_repo.upsert.call_count == 1  # no re-cuenta muestras
    assert notifications.publicar_resultado.call_count == 2  # SNS always-on


@pytest.mark.integration
def test_alerta_with_enviada_en_null_is_republished_on_retry(
    sample_documento: Documento,
    sample_job: VerificationJobMessage,
) -> None:
    """Alerta insertada con enviada_en NULL → republicar SNS en reintento."""
    historial = Historial(
        id=uuid4(),
        documento_id=sample_documento.id,
        tipo_detectado="cedula",
        campos_extraidos={},
        resultado=ResultadoVerificacion.REVISION_MANUAL,
        score_lectura=None,
        score_autenticidad=None,
        modelo_usado="claude-haiku-test",
        version_extraccion="1.0.0",
        prompt_hash="b" * 64,
        procesado_en=datetime.now(timezone.utc),
    )
    alerta_pendiente = Alerta(
        id=uuid4(),
        historial_id=historial.id,
        dias_aviso=DiasAviso.ZERO,
        estado=EstadoAlerta.PENDIENTE,
        enviada_en=None,
    )

    repo = MagicMock()
    repo.obtener_documento.return_value = sample_documento
    repo.obtener_extraccion_idempotente.return_value = historial
    repo.try_registrar_alerta.return_value = None
    repo.obtener_alerta.return_value = alerta_pendiente

    ocr = MagicMock()
    type(ocr).prompt_hash = PropertyMock(return_value="b" * 64)

    notifications = MagicMock()
    notifications.publicar_resultado.return_value = "sns-r"
    notifications.publicar_alerta.side_effect = [
        RetryableNotificationError("sns down"),
        "sns-alerta-ok",
    ]

    pipeline = _pipeline(repo=repo, ocr=ocr, notifications=notifications)

    with pytest.raises(RetryableNotificationError):
        pipeline.process_job(sample_job)
    assert notifications.publicar_alerta.call_count == 1

    # Reintento: enviada_en sigue NULL → vuelve a publicar
    notifications.publicar_alerta.side_effect = None
    notifications.publicar_alerta.return_value = "sns-alerta-ok"
    pipeline.process_job(sample_job)
    assert notifications.publicar_alerta.call_count == 2
    repo.marcar_alerta_enviada.assert_called_with(alerta_pendiente.id)


@pytest.mark.integration
def test_alerta_with_enviada_en_set_skips_republication(
    sample_documento: Documento,
    sample_job: VerificationJobMessage,
) -> None:
    """Alerta ya enviada (enviada_en set) → skip sin publicar_alerta."""
    historial = Historial(
        id=uuid4(),
        documento_id=sample_documento.id,
        tipo_detectado="cedula",
        campos_extraidos={},
        resultado=ResultadoVerificacion.REVISION_MANUAL,
        score_lectura=None,
        score_autenticidad=None,
        modelo_usado="claude-haiku-test",
        version_extraccion="1.0.0",
        prompt_hash="c" * 64,
        procesado_en=datetime.now(timezone.utc),
    )
    alerta_enviada = Alerta(
        id=uuid4(),
        historial_id=historial.id,
        dias_aviso=DiasAviso.ZERO,
        estado=EstadoAlerta.ENVIADA,
        enviada_en=datetime.now(timezone.utc),
    )

    repo = MagicMock()
    repo.obtener_documento.return_value = sample_documento
    repo.obtener_extraccion_idempotente.return_value = historial
    repo.try_registrar_alerta.return_value = None
    repo.obtener_alerta.return_value = alerta_enviada

    ocr = MagicMock()
    type(ocr).prompt_hash = PropertyMock(return_value="c" * 64)
    notifications = MagicMock()
    notifications.publicar_resultado.return_value = "sns-r"

    pipeline = _pipeline(repo=repo, ocr=ocr, notifications=notifications)
    pipeline.process_job(sample_job)

    notifications.publicar_resultado.assert_called_once()
    notifications.publicar_alerta.assert_not_called()
    repo.marcar_alerta_enviada.assert_not_called()
