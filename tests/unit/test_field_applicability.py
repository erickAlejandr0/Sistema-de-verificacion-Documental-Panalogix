"""Unit tests: campos aplicables por tipo."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.models.fields import CampoExtraido
from app.services.field_applicability import (
    confidences_for_aplicables,
    min_confidence_aplicables,
    resolve_campos_aplicables,
)


def test_licencia_ignora_placa() -> None:
    """Placa no es aplicable a licencia."""
    aplicables = resolve_campos_aplicables("licencia")
    assert "placa" not in aplicables
    assert "cedula" in aplicables
    assert "fecha_vencimiento" in aplicables

    campos = {
        "cedula": CampoExtraido(valor="8-1-1", confianza=Decimal("0.990")),
        "placa": CampoExtraido(valor=None, confianza=Decimal("0.000")),
        "nombre_titular": CampoExtraido(valor="A", confianza=Decimal("0.980")),
        "categoria": CampoExtraido(valor="E3", confianza=Decimal("0.950")),
        "fecha_emision": CampoExtraido(valor="01/01/2020", confianza=Decimal("0.900")),
        "fecha_vencimiento": CampoExtraido(
            valor="01/01/2028", confianza=Decimal("0.970")
        ),
    }
    min_conf = min_confidence_aplicables(campos, aplicables)
    assert min_conf == Decimal("0.900")
    assert min_conf > Decimal("0.000")


def test_soat_incluye_placa() -> None:
    """SOAT incluye placa; no incluye categoria."""
    aplicables = resolve_campos_aplicables("soat")
    assert "placa" in aplicables
    assert "categoria" not in aplicables


def test_jsonb_override_gana() -> None:
    """reglas_validacion.campos_aplicables reemplaza el default."""
    aplicables = resolve_campos_aplicables(
        "licencia",
        {"campos_aplicables": ["cedula", "placa"]},
    )
    assert aplicables == frozenset({"cedula", "placa"})


def test_desconocido_vacio_documentado() -> None:
    """desconocido → frozenset vacío (fallback en callers; RN-03 rechaza)."""
    assert resolve_campos_aplicables("desconocido") == frozenset()


def test_aplicable_ausente_cuenta_cero() -> None:
    """Campo aplicable faltante en extracción → confianza 0.000."""
    aplicables = frozenset({"cedula", "fecha_vencimiento"})
    campos = {
        "cedula": CampoExtraido(valor="8-1-1", confianza=Decimal("0.990")),
    }
    values = confidences_for_aplicables(campos, aplicables)
    assert Decimal("0.000") in values
    assert Decimal("0.990") in values


def test_sinonimo_numero_poliza_cuenta_para_poliza() -> None:
    """numero_poliza satisface el canónico poliza (red de seguridad)."""
    values = confidences_for_aplicables(
        {"numero_poliza": CampoExtraido(valor="P-1", confianza=Decimal("0.970"))},
        ["poliza"],
    )
    assert values == [Decimal("0.970")]


def test_sinonimo_centro_autorizado() -> None:
    """centro_autorizado satisface centro."""
    values = confidences_for_aplicables(
        {
            "centro_autorizado": CampoExtraido(
                valor="Centro A", confianza=Decimal("0.880")
            )
        },
        ["centro"],
    )
    assert values == [Decimal("0.880")]


def test_sinonimo_empresa_aseguradora() -> None:
    """empresa_aseguradora satisface aseguradora."""
    values = confidences_for_aplicables(
        {
            "empresa_aseguradora": CampoExtraido(
                valor="Seguros SA", confianza=Decimal("0.910")
            )
        },
        ["aseguradora"],
    )
    assert values == [Decimal("0.910")]


def test_warning_cuando_aplicable_ausente(caplog: pytest.LogCaptureFixture) -> None:
    """Falta de canónico/sinónimo emite campo_aplicable_ausente."""
    import logging

    with caplog.at_level(logging.WARNING, logger="app.services.field_applicability"):
        confidences_for_aplicables({}, ["poliza"])
    assert any("campo_aplicable_ausente" in r.message for r in caplog.records)
