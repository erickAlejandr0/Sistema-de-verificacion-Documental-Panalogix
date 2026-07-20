"""Servicio de cálculo de scores de verificación.

Calcula de forma independiente ``score_lectura`` y ``score_autenticidad``,
y clasifica en APROBADO, RECHAZADO o REVISION_MANUAL.

Garantía de confianza (camino A / P3.4):
    ``score_lectura`` itera **directamente** sobre ``campos_extraidos``
    filtrado por ``campos_aplicables`` del tipo (JSONB / defaults). No usa
    ``normalized`` ni el puente ``label_original``. Campos no aplicables
    no cuentan; aplicables ausentes cuentan como confianza ``0.000``.
    Si ``campos_aplicables`` está vacío (p. ej. ``desconocido``), fallback
    a todas las claves presentes — RN-03 ya rechaza ese tipo. RN-05 se
    materializa aquí vía umbral de autenticidad.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import ResultadoVerificacion
from app.models.fields import CampoExtraido, ScoreDecimal
from app.services.field_applicability import confidences_for_aplicables
from app.services.rules_engine import RulesEvaluation

_QUANTIZE = Decimal("0.001")
_ONE = Decimal("1.000")
_ZERO = Decimal("0.000")


class ScoringResult(BaseModel):
    """Scores independientes y clasificación final."""

    model_config = ConfigDict(str_strip_whitespace=True)

    score_lectura: ScoreDecimal
    score_autenticidad: ScoreDecimal
    resultado: ResultadoVerificacion
    alerts: list[str] = Field(default_factory=list)


def _quantize(value: Decimal) -> Decimal:
    """Cuantiza a NUMERIC(4,3) con redondeo half-up."""
    return value.quantize(_QUANTIZE, rounding=ROUND_HALF_UP)


def _clamp01(value: Decimal) -> Decimal:
    """Acota un Decimal al intervalo [0, 1]."""
    if value < _ZERO:
        return _ZERO
    if value > _ONE:
        return _ONE
    return value


class ScoringService:
    """Calcula scores y clasifica el resultado de verificación.

    Orden de clasificación (explícito):
        1. ``has_reject`` → RECHAZADO
        2. ``has_manual`` o autenticidad < umbral → REVISION_MANUAL
        3. else → APROBADO

    Args:
        authenticity_threshold: Umbral de autenticidad (default: settings).
        auth_penalty_anomalia: Penalización por anomalía.
        auth_penalty_temporal: Penalización por validación temporal fallida.
        auth_penalty_exif: Penalización por EXIF sospechoso.
    """

    def __init__(
        self,
        *,
        authenticity_threshold: float | Decimal | None = None,
        auth_penalty_anomalia: float | Decimal | None = None,
        auth_penalty_temporal: float | Decimal | None = None,
        auth_penalty_exif: float | Decimal | None = None,
    ) -> None:
        """Inicializa umbrales y penalizaciones desde settings o override."""
        from app.config import get_worker_settings

        ws = get_worker_settings()
        self._threshold = Decimal(
            str(
                authenticity_threshold
                if authenticity_threshold is not None
                else ws.authenticity_threshold
            )
        )
        self._penalty_anomalia = Decimal(
            str(
                auth_penalty_anomalia
                if auth_penalty_anomalia is not None
                else ws.auth_penalty_anomalia
            )
        )
        self._penalty_temporal = Decimal(
            str(
                auth_penalty_temporal
                if auth_penalty_temporal is not None
                else ws.auth_penalty_temporal
            )
        )
        self._penalty_exif = Decimal(
            str(
                auth_penalty_exif
                if auth_penalty_exif is not None
                else ws.auth_penalty_exif
            )
        )

    def evaluate(
        self,
        rules: RulesEvaluation,
        campos_extraidos: Mapping[str, CampoExtraido],
        *,
        campos_aplicables: Sequence[str] | frozenset[str] | None = None,
        anomalias: Sequence[str] | None = None,
        validacion_temporal_ok: bool | None = None,
        exif_suspicious: bool = False,
    ) -> ScoringResult:
        """Calcula scores y clasifica según reglas + autenticidad.

        Args:
            rules: Evaluación del RulesEngine.
            campos_extraidos: Campos OCR (fuente de ``score_lectura``).
            campos_aplicables: Labels canónicos que cuentan en lectura.
                ``None`` o vacío → media sobre todas las claves presentes
                (fallback ``desconocido`` / RN-03).
            anomalias: Señales de manipulación del modelo.
            validacion_temporal_ok: Consistencia emisión/vencimiento.
            exif_suspicious: Metadatos EXIF sospechosos.

        Returns:
            Scores cuantizados y ``ResultadoVerificacion``.
        """
        score_lectura = self.score_lectura(
            campos_extraidos,
            campos_aplicables=campos_aplicables,
        )
        score_autenticidad = self.score_autenticidad(
            anomalias=anomalias or (),
            validacion_temporal_ok=validacion_temporal_ok,
            exif_suspicious=exif_suspicious,
        )
        resultado = self._classify(rules, score_autenticidad)
        alerts = [d.message for d in rules.alerts]
        return ScoringResult(
            score_lectura=score_lectura,
            score_autenticidad=score_autenticidad,
            resultado=resultado,
            alerts=alerts,
        )

    def score_lectura(
        self,
        campos_extraidos: Mapping[str, CampoExtraido],
        *,
        campos_aplicables: Sequence[str] | frozenset[str] | None = None,
    ) -> Decimal:
        """Media de confianzas OCR sobre campos aplicables.

        Args:
            campos_extraidos: Dict label → ``CampoExtraido``.
            campos_aplicables: Labels canónicos. Vacío/None → todas las
                claves presentes (decisión ``desconocido`` + RN-03).

        Returns:
            Media cuantizada a 3 decimales, o ``0.000`` si no hay valores.
        """
        if campos_aplicables:
            values = confidences_for_aplicables(
                campos_extraidos,
                campos_aplicables,
            )
        else:
            if not campos_extraidos:
                return _ZERO
            values = [
                Decimal(str(campo.confianza)) for campo in campos_extraidos.values()
            ]
        if not values:
            return _ZERO
        total = sum(values, start=_ZERO)
        mean = total / Decimal(len(values))
        return _quantize(_clamp01(mean))

    def score_autenticidad(
        self,
        *,
        anomalias: Sequence[str] = (),
        validacion_temporal_ok: bool | None = None,
        exif_suspicious: bool = False,
    ) -> Decimal:
        """Score de autenticidad partiendo de 1.000 menos penalizaciones.

        Args:
            anomalias: Lista de anomalías detectadas.
            validacion_temporal_ok: ``False`` aplica penalización temporal.
            exif_suspicious: ``True`` aplica penalización EXIF.

        Returns:
            Score en [0.000, 1.000] cuantizado.
        """
        score = _ONE
        score -= self._penalty_anomalia * Decimal(len(anomalias))
        if validacion_temporal_ok is False:
            score -= self._penalty_temporal
        if exif_suspicious:
            score -= self._penalty_exif
        return _quantize(_clamp01(score))

    def _classify(
        self,
        rules: RulesEvaluation,
        score_autenticidad: Decimal,
    ) -> ResultadoVerificacion:
        """Aplica el orden de clasificación del contrato P3.4."""
        if rules.has_reject:
            return ResultadoVerificacion.RECHAZADO
        if rules.has_manual or score_autenticidad < self._threshold:
            return ResultadoVerificacion.REVISION_MANUAL
        return ResultadoVerificacion.APROBADO
