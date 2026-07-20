"""Parser OCR: entidad_emisora a nivel raíz."""

from __future__ import annotations

from decimal import Decimal

from app.services.ocr import _parse_extraction_payload


def test_parse_entidad_emisora_present() -> None:
    campos, tipo, anomalias, emisor = _parse_extraction_payload(
        {
            "tipo_detectado": "licencia",
            "entidad_emisora": "  ATTT  ",
            "campos": {
                "cedula": {"valor": "8-1-1", "confianza": "0.990"},
            },
            "anomalias": [],
        }
    )
    assert tipo == "licencia"
    assert emisor == "ATTT"
    assert anomalias == []
    assert campos["cedula"].valor == "8-1-1"
    assert campos["cedula"].confianza == Decimal("0.990")


def test_parse_entidad_emisora_empty_becomes_none() -> None:
    _, _, _, emisor = _parse_extraction_payload(
        {
            "tipo_detectado": "soat",
            "entidad_emisora": "   ",
            "campos": {},
            "anomalias": [],
        }
    )
    assert emisor is None


def test_parse_entidad_emisora_missing() -> None:
    _, _, _, emisor = _parse_extraction_payload(
        {
            "tipo_detectado": "cedula",
            "campos": {},
            "anomalias": [],
        }
    )
    assert emisor is None
