"""Contrato: POST .../resolver — corregido_por str, 422, 404."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.handlers import api_handler
from app.handlers.api_handler import ApiPipeline
from app.models.correccion import Correccion
from app.models.documento import Documento
from app.models.enums import ResultadoVerificacion
from app.models.historial import Historial
from app.repositories.exceptions import HistorialNotFoundError
from tests.conftest import make_api_event


@pytest.fixture
def retool_key(api_env: None) -> str:
    from app.config import get_api_settings

    get_api_settings.cache_clear()
    return get_api_settings().retool_api_key


@pytest.mark.contract
def test_resolver_accepts_corregido_por_string_and_persists(
    retool_key: str,
) -> None:
    """corregido_por es texto Retool (email), no UUID relacional."""
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
        prompt_hash="g" * 64,
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
        campo_corregido="placa",
        valor_modelo="XX0000",
        valor_correcto="AB1234",
        corregido_por="revisor@panalogix.example",
        corregido_en=datetime.now(timezone.utc),
    )

    notifications = MagicMock()
    notifications.publicar_resultado.return_value = "mid"

    pipeline = ApiPipeline(
        verificacion_repo=repo,
        s3_repo=MagicMock(),
        sqs_repo=MagicMock(),
        notifications=notifications,
    )

    with patch.object(api_handler, "ApiPipeline", return_value=pipeline):
        resp = api_handler.handler(
            make_api_event(
                "POST",
                f"/verificaciones/{historial_id}/resolver",
                api_key=retool_key,
                body={
                    "resultado": "APROBADO",
                    "corregido_por": "revisor@panalogix.example",
                    "correcciones": [
                        {
                            "campo_corregido": "placa",
                            "valor_modelo": "XX0000",
                            "valor_correcto": "AB1234",
                        }
                    ],
                },
            ),
            None,
        )

    assert resp["statusCode"] == 200
    repo.registrar_correccion.assert_called_once()
    corr = repo.registrar_correccion.call_args.args[0]
    assert corr.corregido_por == "revisor@panalogix.example"
    assert isinstance(corr.corregido_por, str)


@pytest.mark.contract
def test_resolver_invalid_body_returns_422(retool_key: str) -> None:
    pipeline = ApiPipeline(
        verificacion_repo=MagicMock(),
        s3_repo=MagicMock(),
        sqs_repo=MagicMock(),
        notifications=MagicMock(),
    )
    with patch.object(api_handler, "ApiPipeline", return_value=pipeline):
        resp = api_handler.handler(
            make_api_event(
                "POST",
                f"/verificaciones/{uuid4()}/resolver",
                api_key=retool_key,
                body={"resultado": "REVISION_MANUAL", "corregido_por": "x"},
            ),
            None,
        )
    assert resp["statusCode"] == 422


@pytest.mark.contract
def test_resolver_missing_historial_returns_404(retool_key: str) -> None:
    repo = MagicMock()
    repo.obtener_extraccion.side_effect = HistorialNotFoundError("gone")

    pipeline = ApiPipeline(
        verificacion_repo=repo,
        s3_repo=MagicMock(),
        sqs_repo=MagicMock(),
        notifications=MagicMock(),
    )
    with patch.object(api_handler, "ApiPipeline", return_value=pipeline):
        resp = api_handler.handler(
            make_api_event(
                "POST",
                f"/verificaciones/{uuid4()}/resolver",
                api_key=retool_key,
                body={
                    "resultado": "RECHAZADO",
                    "corregido_por": "revisor@panalogix.example",
                    "correcciones": [],
                },
            ),
            None,
        )
    assert resp["statusCode"] == 404
    body = json.loads(resp["body"])
    assert "error" in body
