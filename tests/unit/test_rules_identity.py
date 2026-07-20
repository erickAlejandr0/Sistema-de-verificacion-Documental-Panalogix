"""Unit tests: identidad persona (RN-02/04/10) vs vehículo (RN-07)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.models.fields import CampoExtraido
from app.models.enums import ResultadoVerificacion
from app.services.normalizer import NormalizedField
from app.services.rules_engine import CarrierContext, RuleSeverity, RulesEngine
from app.services.scoring import ScoringService


def _nf(valor: str | None, label: str) -> NormalizedField | None:
    if valor is None:
        return None
    return NormalizedField(valor=valor, label_original=label)


def _base_normalized(**overrides: NormalizedField | None) -> dict[str, NormalizedField | None]:
    base: dict[str, NormalizedField | None] = {
        "fecha_vencimiento": _nf("01/01/2028", "fecha_vencimiento"),
        "nombre_titular": None,
        "cedula": None,
        "placa": None,
        "categoria": None,
    }
    base.update(overrides)
    return base


def test_revisado_salta_rn02_y_rn04_ejecuta_rn07() -> None:
    """revisado: sin persona en campos_aplicables; RN-07 sí corre."""
    engine = RulesEngine()
    evaluation = engine.evaluate(
        campos_extraidos={
            "resultado": CampoExtraido(valor="Aprobado", confianza=Decimal("0.990")),
            "centro": CampoExtraido(valor="Centro A", confianza=Decimal("0.980")),
        },
        normalized=_base_normalized(
            placa=_nf("PA-1111", "placa"),
        ),
        context=CarrierContext(placa="PA-1111"),
        tipo_detectado="revisado",
        hoy=date(2026, 7, 18),
    )
    by_id = {d.rule_id: d for d in evaluation.details}
    assert by_id["RN-02"].passed is True
    assert "omitida" in by_id["RN-02"].message
    assert by_id["RN-04"].passed is True
    assert "omitida" in by_id["RN-04"].message
    assert "RN-07" in by_id
    assert by_id["RN-07"].passed is True


def test_permiso_pesos_salta_persona() -> None:
    """permiso_pesos: RN-02/04 omitidas; RN-07 activa."""
    engine = RulesEngine()
    evaluation = engine.evaluate(
        campos_extraidos={},
        normalized=_base_normalized(placa=_nf("PA-9999", "placa")),
        context=CarrierContext(placa="PA-9999"),
        tipo_detectado="permiso_pesos",
        hoy=date(2026, 7, 18),
    )
    by_id = {d.rule_id: d for d in evaluation.details}
    assert by_id["RN-02"].passed is True
    assert by_id["RN-04"].passed is True
    assert by_id["RN-07"].passed is True


def test_rn04_sin_contexto_es_manual() -> None:
    """Tipo persona sin cedula/nombre en contexto → MANUAL."""
    engine = RulesEngine()
    evaluation = engine.evaluate(
        campos_extraidos={},
        normalized=_base_normalized(
            cedula=_nf("8-1-1", "cedula"),
            nombre_titular=_nf("NOMBRE", "nombre_titular"),
            categoria=_nf("E3", "categoria"),
        ),
        context=CarrierContext(),
        tipo_detectado="licencia",
        hoy=date(2026, 7, 18),
    )
    rn04 = next(d for d in evaluation.details if d.rule_id == "RN-04")
    assert rn04.passed is False
    assert rn04.severity == RuleSeverity.MANUAL
    assert "contexto de titular no recibido" in rn04.message
    assert evaluation.has_manual is True


def test_rn04_mismatch_es_reject() -> None:
    """Tipo persona con contexto que no coincide → REJECT."""
    engine = RulesEngine()
    evaluation = engine.evaluate(
        campos_extraidos={},
        normalized=_base_normalized(
            cedula=_nf("8-1-1", "cedula"),
            nombre_titular=_nf("NOMBRE DOC", "nombre_titular"),
            categoria=_nf("E3", "categoria"),
        ),
        context=CarrierContext(nombre="OTRO NOMBRE"),
        tipo_detectado="licencia",
        hoy=date(2026, 7, 18),
    )
    rn04 = next(d for d in evaluation.details if d.rule_id == "RN-04")
    assert rn04.passed is False
    assert rn04.severity == RuleSeverity.REJECT
    assert evaluation.has_reject is True


def test_rn07_sin_contexto_placa_es_manual() -> None:
    """Tipo con placa y sin context.placa → MANUAL."""
    engine = RulesEngine()
    evaluation = engine.evaluate(
        campos_extraidos={},
        normalized=_base_normalized(placa=_nf("PA-1111", "placa")),
        context=CarrierContext(),
        tipo_detectado="permiso_pesos",
        hoy=date(2026, 7, 18),
    )
    rn07 = next(d for d in evaluation.details if d.rule_id == "RN-07")
    assert rn07.passed is False
    assert rn07.severity == RuleSeverity.MANUAL
    assert "contexto de placa no recibido" in rn07.message


def test_rn07_soat_placa_mismatch_es_reject() -> None:
    """SOAT con placa distinta al contexto → REJECT."""
    engine = RulesEngine()
    evaluation = engine.evaluate(
        campos_extraidos={},
        normalized=_base_normalized(
            placa=_nf("PA-1111", "placa"),
            nombre_titular=_nf("TITULAR", "nombre_titular"),
        ),
        context=CarrierContext(placa="PA-2222", nombre="TITULAR"),
        tipo_detectado="soat",
        hoy=date(2026, 7, 18),
    )
    rn07 = next(d for d in evaluation.details if d.rule_id == "RN-07")
    assert rn07.passed is False
    assert rn07.severity == RuleSeverity.REJECT


def test_rn07_revisado_placa_mismatch_es_reject() -> None:
    """revisado (tipo nuevo con RN-07) mismatch de placa → REJECT."""
    engine = RulesEngine()
    evaluation = engine.evaluate(
        campos_extraidos={
            "resultado": CampoExtraido(valor="Aprobado", confianza=Decimal("0.990")),
        },
        normalized=_base_normalized(placa=_nf("PA-AAAA", "placa")),
        context=CarrierContext(placa="PA-BBBB"),
        tipo_detectado="revisado",
        hoy=date(2026, 7, 18),
    )
    rn07 = next(d for d in evaluation.details if d.rule_id == "RN-07")
    assert rn07.passed is False
    assert rn07.severity == RuleSeverity.REJECT
    assert evaluation.has_reject is True


def test_has_reject_gana_sobre_has_manual() -> None:
    """RN-04 REJECT + RN-07 MANUAL coexisten; scoring prioriza REJECT."""
    engine = RulesEngine()
    # soat espera persona y placa: mismatch de nombre + sin placa en contexto
    evaluation = engine.evaluate(
        campos_extraidos={},
        normalized=_base_normalized(
            placa=_nf("PA-1111", "placa"),
            nombre_titular=_nf("NOMBRE DOC", "nombre_titular"),
        ),
        context=CarrierContext(nombre="OTRO"),
        tipo_detectado="soat",
        hoy=date(2026, 7, 18),
    )
    by_id = {d.rule_id: d for d in evaluation.details}
    assert by_id["RN-04"].severity == RuleSeverity.REJECT
    assert by_id["RN-04"].passed is False
    assert by_id["RN-07"].severity == RuleSeverity.MANUAL
    assert by_id["RN-07"].passed is False
    assert evaluation.has_reject is True
    assert evaluation.has_manual is True

    scoring = ScoringService(authenticity_threshold=0.70)
    result = scoring.evaluate(
        evaluation,
        {"placa": CampoExtraido(valor="PA-1111", confianza=Decimal("0.990"))},
        campos_aplicables=["placa", "aseguradora", "poliza", "fecha_emision", "fecha_vencimiento", "nombre_titular"],
    )
    assert result.resultado == ResultadoVerificacion.RECHAZADO


def test_rn10_sin_contexto_cedula_es_manual() -> None:
    """CRCT sin cédula en contexto → RN-10 MANUAL (vía helper RN-04)."""
    engine = RulesEngine()
    evaluation = engine.evaluate(
        campos_extraidos={},
        normalized=_base_normalized(
            cedula=_nf("8-1-1", "cedula"),
            nombre_titular=_nf("NOMBRE", "nombre_titular"),
        ),
        context=CarrierContext(),
        tipo_detectado="crct",
        hoy=date(2026, 7, 18),
    )
    rn10 = next(d for d in evaluation.details if d.rule_id == "RN-10")
    assert rn10.passed is False
    assert rn10.severity == RuleSeverity.MANUAL
    assert "contexto de titular no recibido" in rn10.message
