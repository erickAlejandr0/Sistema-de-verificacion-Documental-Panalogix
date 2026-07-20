"""Tests unitarios de EMF (métricas embebidas) — sin CloudWatch real."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.handlers.api_handler import ApiPipeline
from app.models.correccion import Correccion
from app.models.documento import Documento
from app.models.enums import ResultadoVerificacion
from app.models.fields import CampoExtraido
from app.models.historial import Historial
from app.models.patron import Patron
from app.repositories.exceptions import RepositoryError
from app.services.pattern_learning import accumulate_pattern
from app.utils import metrics as metrics_mod
from app.utils.metrics import (
    NAMESPACE,
    emit_count,
    emit_value,
    normalize_campo_corregido_dimension,
)


def _parse_emf_line(line: str) -> dict:
    payload = json.loads(line.strip())
    assert "_aws" in payload
    assert "level" not in payload  # no mezclar con JsonFormatter
    assert "message" not in payload
    return payload


def test_normalize_campo_corregido_dimension_whitelist() -> None:
    assert normalize_campo_corregido_dimension("cedula") == "cedula"
    assert normalize_campo_corregido_dimension("  CEDULA  ") == "cedula"
    assert normalize_campo_corregido_dimension("campo_inventado_xyz") == "other"
    assert normalize_campo_corregido_dimension("") == "other"


def test_emit_count_emf_shape(capsys: pytest.CaptureFixture[str]) -> None:
    emit_count(
        "VerificacionesPorResultado",
        dimensions={"tipo_documento": "licencia", "resultado": "APROBADO"},
    )
    out = capsys.readouterr().out.strip()
    payload = _parse_emf_line(out)
    cw = payload["_aws"]["CloudWatchMetrics"][0]
    assert cw["Namespace"] == NAMESPACE
    assert cw["Dimensions"] == [["tipo_documento", "resultado"]]
    assert cw["Metrics"] == [
        {"Name": "VerificacionesPorResultado", "Unit": "Count"}
    ]
    assert payload["tipo_documento"] == "licencia"
    assert payload["resultado"] == "APROBADO"
    assert payload["VerificacionesPorResultado"] == 1.0
    assert isinstance(payload["_aws"]["Timestamp"], int)


def test_emit_value_emf_shape(capsys: pytest.CaptureFixture[str]) -> None:
    emit_value(
        "PatronesConfianzaPromedio",
        0.85,
        dimensions={"tipo_codigo": "soat"},
    )
    payload = _parse_emf_line(capsys.readouterr().out.strip())
    cw = payload["_aws"]["CloudWatchMetrics"][0]
    assert cw["Metrics"][0]["Unit"] == "None"
    assert payload["PatronesConfianzaPromedio"] == 0.85


def test_emit_soft_fail_on_json_dumps(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Fallos de serialización no propagan; se loguea warning."""
    with (
        patch.object(metrics_mod.json, "dumps", side_effect=TypeError("boom")),
        caplog.at_level("WARNING"),
    ):
        emit_count("X", dimensions={"a": "b"})
    assert any("metrics_emit_failed" in r.message for r in caplog.records)


def test_accumulate_upsert_emits_two_metrics() -> None:
    repo = MagicMock()
    conf = Decimal("0.920")
    repo.upsert.return_value = Patron(
        id=uuid4(),
        tipo_codigo="licencia",
        subtipo="",
        estructura_detectada={"campos_tipicos": ["cedula"]},
        confianza_promedio=conf,
        muestras=2,
        actualizado_en=datetime.now(timezone.utc),
    )
    with (
        patch("app.services.pattern_learning.emit_count") as mock_count,
        patch("app.services.pattern_learning.emit_value") as mock_value,
    ):
        accumulate_pattern(
            patron_repo=repo,
            tipo_detectado="licencia",
            campos={
                "cedula": CampoExtraido(
                    valor="8-1", confianza=Decimal("0.9")
                )
            },
            score_lectura=Decimal("0.900"),
        )
    mock_count.assert_called_once_with(
        "PatronesActualizados",
        dimensions={"tipo_codigo": "licencia"},
    )
    mock_value.assert_called_once_with(
        "PatronesConfianzaPromedio",
        float(conf),
        dimensions={"tipo_codigo": "licencia"},
    )


def test_accumulate_desconocido_emits_documentos_tipo() -> None:
    repo = MagicMock()
    with patch("app.services.pattern_learning.emit_count") as mock_count:
        accumulate_pattern(
            patron_repo=repo,
            tipo_detectado="desconocido",
            campos={},
            score_lectura=Decimal("0.500"),
            tipo_declarado="licencia",
        )
    repo.upsert.assert_not_called()
    mock_count.assert_called_once_with(
        "DocumentosTipoDesconocido",
        dimensions={"tipo_declarado": "licencia"},
    )


def test_accumulate_desconocido_empty_declarado_is_none() -> None:
    with patch("app.services.pattern_learning.emit_count") as mock_count:
        accumulate_pattern(
            patron_repo=MagicMock(),
            tipo_detectado="desconocido",
            campos={},
            score_lectura=Decimal("0.500"),
            tipo_declarado=None,
        )
    mock_count.assert_called_once_with(
        "DocumentosTipoDesconocido",
        dimensions={"tipo_declarado": "none"},
    )


def test_accumulate_soft_fail_repo_emits_zero_patron_metrics() -> None:
    repo = MagicMock()
    repo.upsert.side_effect = RepositoryError("boom")
    with (
        patch("app.services.pattern_learning.emit_count") as mock_count,
        patch("app.services.pattern_learning.emit_value") as mock_value,
    ):
        accumulate_pattern(
            patron_repo=repo,
            tipo_detectado="soat",
            campos={
                "placa": CampoExtraido(valor="AB1234", confianza=Decimal("0.9"))
            },
            score_lectura=Decimal("0.900"),
        )
    mock_count.assert_not_called()
    mock_value.assert_not_called()


def test_pipeline_emits_verificaciones_por_resultado(
    sample_documento: Documento,
    sample_job,
    sample_extraction,
    sample_rules,
    sample_scoring,
    sample_historial: Historial,
) -> None:
    """Tras INSERT genuino (no idempotente) se emite VerificacionesPorResultado."""
    from app.handlers.lambda_handler import VerificationPipeline
    from unittest.mock import PropertyMock

    repo = MagicMock()
    repo.obtener_documento.return_value = sample_documento
    repo.obtener_extraccion_idempotente.return_value = None
    repo.obtener_reglas_validacion.return_value = {}
    repo.registrar_extraccion.return_value = sample_historial

    ocr = MagicMock()
    type(ocr).prompt_hash = PropertyMock(return_value="a" * 64)
    ocr.extract.return_value = sample_extraction

    pipeline = VerificationPipeline(
        verificacion_repo=repo,
        s3_repo=MagicMock(descargar_raw=MagicMock(return_value=b"jpeg")),
        ocr=ocr,
        rules_engine=MagicMock(evaluate=MagicMock(return_value=sample_rules)),
        scoring=MagicMock(evaluate=MagicMock(return_value=sample_scoring)),
        notifications=MagicMock(),
        patron_repo=MagicMock(),
        extraction_version="1.0.0",
    )
    with patch("app.handlers.lambda_handler.emit_count") as mock_emit:
        pipeline.process_job(sample_job)

    mock_emit.assert_any_call(
        "VerificacionesPorResultado",
        dimensions={
            "tipo_documento": sample_extraction.tipo_detectado,
            "resultado": "APROBADO",
        },
    )


def test_non_retryable_emits_verificaciones_por_resultado(
    sample_documento: Documento,
    sample_job,
) -> None:
    from app.handlers.lambda_handler import VerificationPipeline
    from app.utils.image import CorruptDocumentError
    from unittest.mock import PropertyMock

    historial = Historial(
        id=uuid4(),
        documento_id=sample_documento.id,
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
    repo = MagicMock()
    repo.obtener_documento.return_value = sample_documento
    repo.obtener_extraccion_idempotente.return_value = None
    repo.registrar_extraccion.return_value = historial
    repo.try_registrar_alerta.return_value = None

    ocr = MagicMock()
    type(ocr).prompt_hash = PropertyMock(return_value="d" * 64)

    pipeline = VerificationPipeline(
        verificacion_repo=repo,
        s3_repo=MagicMock(),
        ocr=ocr,
        rules_engine=MagicMock(),
        scoring=MagicMock(),
        notifications=MagicMock(),
        patron_repo=MagicMock(),
        extraction_version="1.0.0",
    )
    with patch("app.handlers.lambda_handler.emit_count") as mock_emit:
        pipeline.handle_non_retryable_document_failure(
            sample_job, error=CorruptDocumentError("roto")
        )

    mock_emit.assert_called_once_with(
        "VerificacionesPorResultado",
        dimensions={
            "tipo_documento": "cedula",
            "resultado": "REVISION_MANUAL",
        },
    )


def test_resolver_emits_correcciones_and_resoluciones() -> None:
    """Una sola carga de historial; campo inventado → other; dims anterior/nuevo."""
    historial_id = uuid4()
    documento_id = uuid4()
    historial = Historial(
        id=historial_id,
        documento_id=documento_id,
        tipo_detectado="cedula",
        campos_extraidos={},
        resultado=ResultadoVerificacion.REVISION_MANUAL,
        score_lectura=Decimal("0.800"),
        score_autenticidad=Decimal("0.700"),
        modelo_usado="claude",
        version_extraccion="1.0.0",
        prompt_hash="a" * 64,
        procesado_en=datetime.now(timezone.utc),
    )
    updated = historial.model_copy(
        update={"resultado": ResultadoVerificacion.APROBADO}
    )
    documento = Documento(
        id=documento_id,
        transportista_id=uuid4(),
        tipo_documento="cedula",
        s3_key_raw="uploads/a.jpg",
        subido_en=datetime.now(timezone.utc),
        eliminar_despues=date(2026, 12, 1),
    )

    repo = MagicMock()
    repo.obtener_extraccion.return_value = (historial, None)
    repo.actualizar_resultado_historial.return_value = updated
    repo.obtener_documento.return_value = documento
    repo.registrar_correccion.return_value = Correccion(
        id=uuid4(),
        historial_id=historial_id,
        campo_corregido="campo_inventado_xyz",
        valor_modelo="x",
        valor_correcto="y",
        corregido_por="revisor@example.com",
        corregido_en=datetime.now(timezone.utc),
    )

    pipeline = ApiPipeline(
        verificacion_repo=repo,
        s3_repo=MagicMock(),
        sqs_repo=MagicMock(),
        notifications=MagicMock(),
    )

    with patch("app.handlers.api_handler.emit_count") as mock_emit:
        resp = pipeline.resolver(
            historial_id,
            {
                "resultado": "APROBADO",
                "corregido_por": "revisor@example.com",
                "correcciones": [
                    {
                        "campo_corregido": "campo_inventado_xyz",
                        "valor_modelo": "x",
                        "valor_correcto": "y",
                    },
                    {
                        "campo_corregido": "cedula",
                        "valor_modelo": "1",
                        "valor_correcto": "2",
                    },
                ],
            },
        )

    assert resp["statusCode"] == 200
    repo.obtener_extraccion.assert_called_once_with(
        historial_id, decrypt_pii=False
    )
    assert mock_emit.call_count == 3
    calls = mock_emit.call_args_list
    assert calls[0].args[0] == "CorreccionesRegistradas"
    assert calls[0].kwargs["dimensions"]["campo_corregido"] == "other"
    assert calls[1].args[0] == "CorreccionesRegistradas"
    assert calls[1].kwargs["dimensions"]["campo_corregido"] == "cedula"
    assert calls[2].args[0] == "ResolucionesManuales"
    assert calls[2].kwargs["dimensions"] == {
        "tipo_documento": "cedula",
        "resultado_anterior": "REVISION_MANUAL",
        "resultado_nuevo": "APROBADO",
    }
