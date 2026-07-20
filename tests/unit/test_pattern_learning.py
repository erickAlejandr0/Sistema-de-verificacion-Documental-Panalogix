"""Tests unitarios de acumulación de patrones (RF-22)."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

from app.models.fields import CampoExtraido
from app.models.patron import PatronCreate
from app.repositories.exceptions import RepositoryError
from app.services.pattern_learning import (
    accumulate_pattern,
    build_estructura_detectada,
)


def test_licencia_placa_null_excluded_from_campos_tipicos() -> None:
    """Licencia con placa=null: campos_tipicos no incluye placa."""
    cedula_valor = "8-123-456"
    nombre_valor = "Juan Perez"
    campos = {
        "cedula": CampoExtraido(valor=cedula_valor, confianza=Decimal("0.990")),
        "nombre_titular": CampoExtraido(
            valor=nombre_valor, confianza=Decimal("0.980")
        ),
        "placa": CampoExtraido(valor=None, confianza=Decimal("0.000")),
        "categoria": CampoExtraido(valor="E3", confianza=Decimal("0.970")),
    }
    estructura = build_estructura_detectada(campos, entidad_emisora="ATTT")
    tipicos = estructura["campos_tipicos"]
    assert tipicos == ["categoria", "cedula", "nombre_titular"]
    assert "placa" not in tipicos
    # Ley 81: solo nombres de campo, nunca valores PII.
    assert all(isinstance(k, str) for k in tipicos)
    serialized = str(estructura)
    assert cedula_valor not in serialized
    assert nombre_valor not in serialized


def test_accumulate_skips_desconocido() -> None:
    repo = MagicMock()
    accumulate_pattern(
        patron_repo=repo,
        tipo_detectado="desconocido",
        campos={"placa": CampoExtraido(valor="AB1234", confianza=Decimal("0.9"))},
        score_lectura=Decimal("0.900"),
    )
    repo.upsert.assert_not_called()


def test_accumulate_skips_tipo_fuera_catalogo() -> None:
    repo = MagicMock()
    accumulate_pattern(
        patron_repo=repo,
        tipo_detectado="pasaporte_extraterrestre",
        campos={"x": CampoExtraido(valor="1", confianza=Decimal("0.9"))},
        score_lectura=Decimal("0.900"),
    )
    repo.upsert.assert_not_called()


def test_accumulate_upserts_catalog_tipo_and_ley81_payload() -> None:
    repo = MagicMock()
    pii_cedula = "8-999-111"
    campos = {
        "cedula": CampoExtraido(valor=pii_cedula, confianza=Decimal("0.990")),
        "placa": CampoExtraido(valor=None, confianza=Decimal("0.000")),
    }
    accumulate_pattern(
        patron_repo=repo,
        tipo_detectado="licencia",
        campos=campos,
        score_lectura=Decimal("0.950"),
        entidad_emisora="ATTT",
    )
    repo.upsert.assert_called_once()
    create: PatronCreate = repo.upsert.call_args.args[0]
    assert create.tipo_codigo == "licencia"
    assert create.subtipo == ""
    assert create.confianza_promedio == Decimal("0.950")
    assert create.estructura_detectada["campos_tipicos"] == ["cedula"]
    assert create.estructura_detectada["emisor"] == "ATTT"
    assert pii_cedula not in str(create.estructura_detectada)
    assert pii_cedula not in str(create.model_dump())


def test_accumulate_soft_fail_does_not_raise() -> None:
    repo = MagicMock()
    repo.upsert.side_effect = RepositoryError("boom")
    accumulate_pattern(
        patron_repo=repo,
        tipo_detectado="soat",
        campos={"placa": CampoExtraido(valor="AB1234", confianza=Decimal("0.9"))},
        score_lectura=Decimal("0.900"),
    )
    repo.upsert.assert_called_once()
