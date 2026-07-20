"""Unit tests: RN-01 vigencia / ilegible → MANUAL."""

from __future__ import annotations

from datetime import date

from app.services.normalizer import NormalizedField
from app.services.rules_engine import CarrierContext, RuleSeverity, RulesEngine


def test_rn01_fecha_null_es_manual() -> None:
    """fecha_vencimiento ausente → MANUAL, no REJECT."""
    engine = RulesEngine()
    evaluation = engine.evaluate(
        campos_extraidos={},
        normalized={
            "fecha_vencimiento": None,
            "nombre_titular": NormalizedField(
                valor="NOMBRE",
                label_original="nombre_titular",
            ),
            "cedula": NormalizedField(valor="8-1-1", label_original="cedula"),
        },
        context=CarrierContext(),
        tipo_detectado="licencia",
        hoy=date(2026, 7, 18),
    )
    rn01 = next(d for d in evaluation.details if d.rule_id == "RN-01")
    assert rn01.passed is False
    assert rn01.severity == RuleSeverity.MANUAL
    assert evaluation.has_manual is True
    # Otras RN del tipo pueden aportar REJECT; lo que importa es RN-01 MANUAL.


def test_rn01_fecha_vencida_es_reject() -> None:
    """fecha_vencimiento parseable en el pasado → REJECT."""
    engine = RulesEngine()
    evaluation = engine.evaluate(
        campos_extraidos={},
        normalized={
            "fecha_vencimiento": NormalizedField(
                valor="01/01/2020",
                label_original="fecha_vencimiento",
            ),
            "nombre_titular": NormalizedField(
                valor="NOMBRE",
                label_original="nombre_titular",
            ),
            "cedula": NormalizedField(valor="8-1-1", label_original="cedula"),
            "categoria": NormalizedField(valor="E3", label_original="categoria"),
        },
        context=CarrierContext(),
        tipo_detectado="licencia",
        hoy=date(2026, 7, 18),
    )
    rn01 = next(d for d in evaluation.details if d.rule_id == "RN-01")
    assert rn01.passed is False
    assert rn01.severity == RuleSeverity.REJECT
    assert evaluation.has_reject is True
