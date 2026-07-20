"""Unit tests: score_lectura filtrado por campos aplicables."""

from __future__ import annotations

from decimal import Decimal

from app.models.fields import CampoExtraido
from app.services.rules_engine import RulesEvaluation
from app.services.scoring import ScoringService


def test_score_lectura_ignora_no_aplicables() -> None:
    """placa con 0.000 no arrastra el score en licencia."""
    scoring = ScoringService(authenticity_threshold=0.70)
    campos = {
        "cedula": CampoExtraido(valor="8-1-1", confianza=Decimal("1.000")),
        "nombre_titular": CampoExtraido(valor="A", confianza=Decimal("1.000")),
        "placa": CampoExtraido(valor=None, confianza=Decimal("0.000")),
    }
    score = scoring.score_lectura(
        campos,
        campos_aplicables=["cedula", "nombre_titular"],
    )
    assert score == Decimal("1.000")


def test_score_lectura_aplicable_ausente_baja_media() -> None:
    """Aplicable faltante cuenta como 0.000 en la media."""
    scoring = ScoringService(authenticity_threshold=0.70)
    campos = {
        "cedula": CampoExtraido(valor="8-1-1", confianza=Decimal("1.000")),
    }
    score = scoring.score_lectura(
        campos,
        campos_aplicables=["cedula", "fecha_vencimiento"],
    )
    assert score == Decimal("0.500")


def test_evaluate_pasa_campos_aplicables() -> None:
    """evaluate respeta campos_aplicables en score_lectura."""
    scoring = ScoringService(authenticity_threshold=0.70)
    result = scoring.evaluate(
        RulesEvaluation(has_reject=False, has_manual=False),
        {
            "cedula": CampoExtraido(valor="8-1-1", confianza=Decimal("1.000")),
            "placa": CampoExtraido(valor=None, confianza=Decimal("0.000")),
        },
        campos_aplicables=["cedula"],
    )
    assert result.score_lectura == Decimal("1.000")


def test_score_lectura_acepta_sinonimo_poliza() -> None:
    """numero_poliza cuenta hacia el canónico poliza en score_lectura."""
    scoring = ScoringService(authenticity_threshold=0.70)
    score = scoring.score_lectura(
        {"numero_poliza": CampoExtraido(valor="X", confianza=Decimal("0.800"))},
        campos_aplicables=["poliza"],
    )
    assert score == Decimal("0.800")
