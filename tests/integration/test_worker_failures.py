"""Integración: fallos no-retryables (ACK) vs retryables (propagación)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, PropertyMock, patch
from uuid import uuid4

import pytest

from app.handlers import lambda_handler as lh
from app.handlers.lambda_handler import VerificationPipeline
from app.models.alerta import Alerta
from app.models.documento import Documento
from app.models.enums import DiasAviso, EstadoAlerta, ResultadoVerificacion
from app.models.historial import Historial
from app.models.job import VerificationJobMessage
from app.repositories.exceptions import RepositoryError
from app.services.ocr import NonRetryableOcrError, RetryableOcrError
from app.utils.image import CorruptDocumentError, DocumentTooManyPagesError
from tests.conftest import make_sqs_event


def _minimal_historial(documento_id) -> Historial:
    return Historial(
        id=uuid4(),
        documento_id=documento_id,
        tipo_detectado="cedula",
        campos_extraidos={},
        resultado=ResultadoVerificacion.REVISION_MANUAL,
        score_lectura=Decimal("0.000"),
        score_autenticidad=Decimal("0.000"),
        modelo_usado="none",
        version_extraccion="1.0.0",
        prompt_hash="d" * 64,
        costo_api=Decimal("0.000000"),
        procesado_en=datetime.now(timezone.utc),
    )


@pytest.mark.integration
@pytest.mark.parametrize(
    "error",
    [
        CorruptDocumentError("pdf roto"),
        DocumentTooManyPagesError("demasiadas páginas"),
        NonRetryableOcrError("4xx"),
    ],
)
def test_non_retryable_document_errors_ack_with_minimal_historial_and_sns(
    error: BaseException,
    sample_documento: Documento,
    sample_job: VerificationJobMessage,
) -> None:
    """Fallo de documento → Historial mínimo REVISION_MANUAL + SNS + ACK."""
    historial = _minimal_historial(sample_documento.id)
    alerta = Alerta(
        id=uuid4(),
        historial_id=historial.id,
        dias_aviso=DiasAviso.ZERO,
        estado=EstadoAlerta.PENDIENTE,
        enviada_en=None,
    )

    repo = MagicMock()
    repo.obtener_documento.return_value = sample_documento
    repo.obtener_extraccion_idempotente.return_value = None
    repo.registrar_extraccion.return_value = historial
    repo.try_registrar_alerta.return_value = alerta

    ocr = MagicMock()
    type(ocr).prompt_hash = PropertyMock(return_value="d" * 64)
    ocr.extract.side_effect = error

    s3 = MagicMock()
    s3.descargar_raw.return_value = b"bad"

    notifications = MagicMock()
    notifications.publicar_resultado.return_value = "sns-r"
    notifications.publicar_alerta.return_value = "sns-a"
    patron_repo = MagicMock()

    pipeline = VerificationPipeline(
        verificacion_repo=repo,
        s3_repo=s3,
        ocr=ocr,
        rules_engine=MagicMock(),
        scoring=MagicMock(),
        notifications=notifications,
        patron_repo=patron_repo,
        extraction_version="1.0.0",
    )

    with patch.object(lh, "VerificationPipeline", return_value=pipeline):
        result = lh.handler(make_sqs_event(sample_job), None)

    assert result == {}
    repo.registrar_extraccion.assert_called_once()
    create = repo.registrar_extraccion.call_args.args[0]
    assert create.resultado == ResultadoVerificacion.REVISION_MANUAL
    assert create.modelo_usado == "none"
    patron_repo.upsert.assert_not_called()
    notifications.publicar_resultado.assert_called_once()
    notifications.publicar_alerta.assert_called_once()
    repo.marcar_alerta_enviada.assert_called_once_with(alerta.id)


@pytest.mark.integration
def test_retryable_errors_propagate_for_sqs_redrive(
    sample_documento: Documento,
    sample_job: VerificationJobMessage,
) -> None:
    """Errores retryables salen del process_job (SQS reintenta / DLQ infra)."""
    repo = MagicMock()
    repo.obtener_documento.return_value = sample_documento
    repo.obtener_extraccion_idempotente.return_value = None

    ocr = MagicMock()
    type(ocr).prompt_hash = PropertyMock(return_value="e" * 64)
    ocr.extract.side_effect = RetryableOcrError("rate limit")

    s3 = MagicMock()
    s3.descargar_raw.return_value = b"img"

    pipeline = VerificationPipeline(
        verificacion_repo=repo,
        s3_repo=s3,
        ocr=ocr,
        rules_engine=MagicMock(),
        scoring=MagicMock(),
        notifications=MagicMock(),
        patron_repo=MagicMock(),
        extraction_version="1.0.0",
    )

    with pytest.raises(RetryableOcrError):
        pipeline.process_job(sample_job)

    # También vía handler: no capturado → propaga
    with patch.object(lh, "VerificationPipeline", return_value=pipeline):
        with pytest.raises(RetryableOcrError):
            lh.handler(make_sqs_event(sample_job), None)


@pytest.mark.integration
def test_repository_error_propagates(
    sample_documento: Documento,
    sample_job: VerificationJobMessage,
) -> None:
    """RepositoryError no se traga — reintento SQS."""
    repo = MagicMock()
    repo.obtener_documento.side_effect = RepositoryError("db down")

    pipeline = VerificationPipeline(
        verificacion_repo=repo,
        s3_repo=MagicMock(),
        ocr=MagicMock(),
        rules_engine=MagicMock(),
        scoring=MagicMock(),
        notifications=MagicMock(),
        patron_repo=MagicMock(),
        extraction_version="1.0.0",
    )
    type(pipeline._ocr).prompt_hash = PropertyMock(return_value="f" * 64)

    with pytest.raises(RepositoryError):
        pipeline.process_job(sample_job)
