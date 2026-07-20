"""Motor de reglas de validación documental.

Aplica reglas universales y específicas por tipo (RN-01..RN-12),
preferentemente desde ``tipos_documento.reglas_validacion`` (JSONB).

Garantía de confianza (camino A / P3.4):
    Ninguna regla RN-01..RN-12 lee ``confianza`` vía el puente
    ``normalized[concept].label_original``. Las reglas usan solo
    **valores** (``NormalizedField.valor`` o labels crudos en
    ``campos_extraidos``). ``score_lectura`` vive en ScoringService e
    itera ``campos_extraidos`` filtrado por ``campos_aplicables``.
    RN-01 ilegible → MANUAL (mismo criterio que RN-11 / RF-21).
    RN-02/04 se acotan por ``campos_aplicables`` (persona); RN-07 por placa.
    Contexto ausente cuando el tipo lo espera → MANUAL (integración).
"""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.fields import CampoExtraido
from app.services.field_applicability import (
    DEFAULT_CAMPOS_APLICABLES,
    resolve_campos_aplicables,
)
from app.services.normalizer import NormalizedField
from app.utils.dates import (
    InvalidDateFormatError,
    PANAMA_TZ,
    days_until_expiry,
    parse_panama_date,
)
from app.utils.logging import get_logger

logger = get_logger(__name__)

_DEFAULT_CATEGORIAS: tuple[str, ...] = ("E3", "F", "G")
_DEFAULT_RESULTADOS_REVISADO: tuple[str, ...] = (
    "aprobado",
    "aprobado condicionalmente",
)
_DEFAULT_EDAD_MINIMA: int = 18
_DEFAULT_DIAS_ALERTA: int = 30
_TIPO_DESCONOCIDO: str = "desconocido"


class RuleSeverity(str, Enum):
    """Severidad de una regla fallida o de alerta."""

    REJECT = "REJECT"
    ALERT = "ALERT"
    MANUAL = "MANUAL"


class CarrierContext(BaseModel):
    """Contexto del transportista inyectado por Panalogix (sin BD)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    cedula: str | None = None
    placa: str | None = None
    nombre: str | None = None


class RuleDetail(BaseModel):
    """Detalle de evaluación de una regla individual."""

    model_config = ConfigDict(str_strip_whitespace=True)

    rule_id: str
    passed: bool
    severity: RuleSeverity
    message: str


class RulesEvaluation(BaseModel):
    """Resultado agregado del motor de reglas (sin clasificación final)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    details: list[RuleDetail] = Field(default_factory=list)
    has_reject: bool = False
    has_manual: bool = False
    alerts: list[RuleDetail] = Field(default_factory=list)


def _normalize_label(label: str) -> str:
    """Normaliza un label para matching de claves OCR (sin acentos)."""
    decomposed = unicodedata.normalize("NFKD", label)
    without_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    cleaned = without_marks.casefold().strip()
    for sep in (" ", "-", "."):
        cleaned = cleaned.replace(sep, "_")
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned.strip("_")


def _as_text(value: Any) -> str | None:
    """Convierte un valor a texto no vacío, o ``None``."""
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _concept_valor(
    normalized: Mapping[str, NormalizedField | None],
    concept: str,
) -> str | None:
    """Lee el valor de un concepto canónico (None si ausente o vacío)."""
    field = normalized.get(concept)
    if field is None:
        return None
    return _as_text(field.valor)


def _raw_field_valor(
    campos_extraidos: Mapping[str, CampoExtraido],
    *labels: str,
) -> str | None:
    """Busca un valor por labels candidatos en ``campos_extraidos``.

    No usa el puente de confianza; solo valores. Conceptos no canónicos
    del normalizer (p. ej. ``aseguradora``, ``resultado``, ``fecha_nacimiento``)
    se resuelven aquí.
    """
    index = {_normalize_label(key): campo for key, campo in campos_extraidos.items()}
    for label in labels:
        hit = index.get(_normalize_label(label))
        if hit is None:
            continue
        text = _as_text(hit.valor)
        if text is not None:
            return text
    return None


def _norm_id(value: str) -> str:
    """Normaliza identificadores (cédula/placa) para comparación."""
    return "".join(ch for ch in value.casefold() if ch.isalnum())


def _norm_name(value: str) -> str:
    """Normaliza nombres colapsando espacios y casefold."""
    return " ".join(value.casefold().split())


def _merge_rules(
    tipo_detectado: str,
    reglas_validacion: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Combina defaults por tipo con override JSONB (JSONB gana)."""
    tipo = tipo_detectado.casefold().strip()
    defaults: dict[str, Any] = {
        "categorias_validas": list(_DEFAULT_CATEGORIAS),
        "aseguradoras_autorizadas": [],
        "resultados_validos": list(_DEFAULT_RESULTADOS_REVISADO),
        "edad_minima": _DEFAULT_EDAD_MINIMA,
        "dias_alerta_proximidad": _DEFAULT_DIAS_ALERTA,
        "campos_aplicables": list(DEFAULT_CAMPOS_APLICABLES.get(tipo, ())),
    }
    if reglas_validacion:
        defaults.update(dict(reglas_validacion))
    # Garantiza lista canónica resuelta (JSONB gana vía resolve).
    defaults["campos_aplicables"] = sorted(
        resolve_campos_aplicables(tipo, defaults)
    )
    defaults["_tipo"] = tipo
    return defaults


def _age_years(birth: date, today: date) -> int:
    """Edad en años cumplidos a la fecha de referencia."""
    years = today.year - birth.year
    if (today.month, today.day) < (birth.month, birth.day):
        years -= 1
    return years


def _parse_expiry(
    normalized: Mapping[str, NormalizedField | None],
) -> date | None:
    """Parsea ``fecha_vencimiento`` canónica; ``None`` si ausente/inválida."""
    raw = _concept_valor(normalized, "fecha_vencimiento")
    if raw is None:
        return None
    try:
        return parse_panama_date(raw)
    except InvalidDateFormatError:
        return None


def _campos_aplicables_set(rules: Mapping[str, Any]) -> frozenset[str]:
    """Conjunto normalizado de ``campos_aplicables`` ya mergeados."""
    raw = rules.get("campos_aplicables") or ()
    if not isinstance(raw, (list, tuple)):
        return frozenset()
    return frozenset(_normalize_label(str(item)) for item in raw if str(item).strip())


def _tipo_espera_persona(rules: Mapping[str, Any]) -> bool:
    """True si el tipo incluye identidad de persona en campos_aplicables."""
    aplicables = _campos_aplicables_set(rules)
    return bool(aplicables & {"cedula", "nombre_titular"})


def _tipo_espera_placa(rules: Mapping[str, Any]) -> bool:
    """True si el tipo incluye placa en campos_aplicables."""
    return "placa" in _campos_aplicables_set(rules)


class RulesEngine:
    """Evalúa reglas de negocio documentales (RN-01..RN-12).

    No decide APROBADO/RECHAZADO/REVISION_MANUAL por sí solo: expone
    ``RulesEvaluation`` para que ScoringService combine con scores.
    """

    def evaluate(
        self,
        *,
        campos_extraidos: Mapping[str, CampoExtraido],
        normalized: Mapping[str, NormalizedField | None],
        context: CarrierContext,
        tipo_detectado: str,
        reglas_validacion: Mapping[str, Any] | None = None,
        hoy: date | None = None,
    ) -> RulesEvaluation:
        """Ejecuta reglas universales y por tipo.

        Args:
            campos_extraidos: Campos OCR con confianza (no leídos aquí).
            normalized: Conceptos canónicos (valores; ``None`` = ausente).
            context: Cédula/placa/nombre del transportista.
            tipo_detectado: Tipo semántico del documento.
            reglas_validacion: JSONB de ``tipos_documento`` (override).
            hoy: Fecha de referencia (default: hoy en America/Panama).

        Returns:
            Evaluación con detalles, flags reject/manual y alertas.
        """
        today = hoy if hoy is not None else datetime.now(PANAMA_TZ).date()
        rules = _merge_rules(tipo_detectado, reglas_validacion)
        tipo = rules["_tipo"]
        details: list[RuleDetail] = []

        details.append(self._rn01_vigencia(normalized, today))
        details.append(self._rn02_titular(normalized, rules))
        details.append(self._rn03_tipo(tipo))
        details.append(self._rn04_match_titular(normalized, context, rules))

        if tipo == "licencia":
            details.append(self._rn06_categoria(normalized, rules))
        if _tipo_espera_placa(rules):
            details.append(self._rn07_placa(normalized, context, rules))
        if tipo == "soat":
            details.append(self._rn08_aseguradora(campos_extraidos, rules))
        if tipo == "revisado":
            details.append(self._rn09_resultado(campos_extraidos, rules))
        if tipo == "crct":
            details.append(self._rn10_cedula(normalized, context, rules))
        if tipo == "cedula":
            details.append(
                self._rn11_mayoria_edad(campos_extraidos, rules, today)
            )

        alert = self._rn12_proximidad(normalized, rules, today)
        if alert is not None:
            details.append(alert)

        has_reject = any(
            (not d.passed) and d.severity == RuleSeverity.REJECT for d in details
        )
        has_manual = any(
            (not d.passed) and d.severity == RuleSeverity.MANUAL for d in details
        )
        alerts = [
            d
            for d in details
            if d.severity == RuleSeverity.ALERT and not d.passed
        ]

        return RulesEvaluation(
            details=details,
            has_reject=has_reject,
            has_manual=has_manual,
            alerts=alerts,
        )

    def _rn01_vigencia(
        self,
        normalized: Mapping[str, NormalizedField | None],
        today: date,
    ) -> RuleDetail:
        """RN-01: documento vigente; ilegible → MANUAL (no REJECT).

        Campo no legible se trata como mala calidad de imagen, no como
        documento inválido: escala a revisión humana (RF-21), mismo
        criterio que RN-11. Solo un vencimiento parseable y en el pasado
        produce REJECT.
        """
        expiry = _parse_expiry(normalized)
        if expiry is None:
            return RuleDetail(
                rule_id="RN-01",
                passed=False,
                severity=RuleSeverity.MANUAL,
                message=(
                    "fecha_vencimiento ausente o no legible; "
                    "requiere revisión manual"
                ),
            )
        days = days_until_expiry(expiry, today=today)
        if days < 0:
            return RuleDetail(
                rule_id="RN-01",
                passed=False,
                severity=RuleSeverity.REJECT,
                message=f"documento vencido hace {abs(days)} día(s)",
            )
        return RuleDetail(
            rule_id="RN-01",
            passed=True,
            severity=RuleSeverity.REJECT,
            message="documento vigente",
        )

    def _rn02_titular(
        self,
        normalized: Mapping[str, NormalizedField | None],
        rules: Mapping[str, Any],
    ) -> RuleDetail:
        """RN-02: identidad de persona en el documento (si el tipo la espera).

        Skip estructural si ``campos_aplicables`` no incluye cedula ni
        nombre_titular (p. ej. revisado, permiso_pesos). No usa contexto
        de la llamada.
        """
        if not _tipo_espera_persona(rules):
            return RuleDetail(
                rule_id="RN-02",
                passed=True,
                severity=RuleSeverity.REJECT,
                message="tipo sin identidad de persona; RN-02 omitida",
            )
        nombre = _concept_valor(normalized, "nombre_titular")
        cedula = _concept_valor(normalized, "cedula")
        if nombre is None and cedula is None:
            return RuleDetail(
                rule_id="RN-02",
                passed=False,
                severity=RuleSeverity.REJECT,
                message="titular no identificado (sin nombre ni cédula)",
            )
        return RuleDetail(
            rule_id="RN-02",
            passed=True,
            severity=RuleSeverity.REJECT,
            message="titular identificado",
        )

    def _rn03_tipo(self, tipo: str) -> RuleDetail:
        """RN-03: documento reconocido (no desconocido)."""
        if not tipo or tipo == _TIPO_DESCONOCIDO:
            return RuleDetail(
                rule_id="RN-03",
                passed=False,
                severity=RuleSeverity.REJECT,
                message="tipo de documento no reconocido",
            )
        return RuleDetail(
            rule_id="RN-03",
            passed=True,
            severity=RuleSeverity.REJECT,
            message=f"tipo reconocido: {tipo}",
        )

    def _rn04_match_titular(
        self,
        normalized: Mapping[str, NormalizedField | None],
        context: CarrierContext,
        rules: Mapping[str, Any],
        *,
        rule_id: str = "RN-04",
    ) -> RuleDetail:
        """RN-04: titular del documento coincide con el transportista.

        Tres casos (criterio estructural vía ``campos_aplicables``):
        1. Tipo no espera persona → skip.
        2. Tipo espera persona y no hay cedula/nombre en contexto → MANUAL
           (fallo de integración del llamador, no del documento).
        3. Contexto presente y mismatch → REJECT.
        """
        if not _tipo_espera_persona(rules):
            return RuleDetail(
                rule_id=rule_id,
                passed=True,
                severity=RuleSeverity.REJECT,
                message=f"tipo sin identidad de persona; {rule_id} omitida",
            )

        ctx_cedula = _as_text(context.cedula)
        ctx_nombre = _as_text(context.nombre)
        if ctx_cedula is None and ctx_nombre is None:
            return RuleDetail(
                rule_id=rule_id,
                passed=False,
                severity=RuleSeverity.MANUAL,
                message=(
                    "contexto de titular no recibido; "
                    "no se pudo validar coincidencia"
                ),
            )

        doc_cedula = _concept_valor(normalized, "cedula")
        doc_nombre = _concept_valor(normalized, "nombre_titular")
        mismatches: list[str] = []

        if ctx_cedula is not None:
            if doc_cedula is None or _norm_id(doc_cedula) != _norm_id(ctx_cedula):
                mismatches.append("cedula")
        if ctx_nombre is not None:
            if doc_nombre is None or _norm_name(doc_nombre) != _norm_name(ctx_nombre):
                mismatches.append("nombre")

        if mismatches:
            return RuleDetail(
                rule_id=rule_id,
                passed=False,
                severity=RuleSeverity.REJECT,
                message=(
                    f"titular no coincide con contexto ({', '.join(mismatches)})"
                ),
            )
        return RuleDetail(
            rule_id=rule_id,
            passed=True,
            severity=RuleSeverity.REJECT,
            message="titular coincide con contexto",
        )

    def _rn06_categoria(
        self,
        normalized: Mapping[str, NormalizedField | None],
        rules: Mapping[str, Any],
    ) -> RuleDetail:
        """RN-06: categoría de licencia válida para carga."""
        raw_list = rules.get("categorias_validas", _DEFAULT_CATEGORIAS)
        validas = {
            str(c).casefold().strip()
            for c in raw_list
            if _as_text(c) is not None
        }
        categoria = _concept_valor(normalized, "categoria")
        if categoria is None or categoria.casefold() not in validas:
            return RuleDetail(
                rule_id="RN-06",
                passed=False,
                severity=RuleSeverity.REJECT,
                message="categoría de licencia no autorizada para carga",
            )
        return RuleDetail(
            rule_id="RN-06",
            passed=True,
            severity=RuleSeverity.REJECT,
            message="categoría de licencia válida",
        )

    def _rn07_placa(
        self,
        normalized: Mapping[str, NormalizedField | None],
        context: CarrierContext,
        rules: Mapping[str, Any],
    ) -> RuleDetail:
        """RN-07: placa del documento coincide con el vehículo registrado.

        Aplica a cualquier tipo con ``placa`` en ``campos_aplicables``
        (soat, revisado, permiso_pesos). Tres casos análogos a RN-04:
        1. Tipo no espera placa → skip (caller no debería invocar).
        2. Espera placa y contexto ausente → MANUAL (integración).
        3. Contexto presente y mismatch → REJECT.
        """
        if not _tipo_espera_placa(rules):
            return RuleDetail(
                rule_id="RN-07",
                passed=True,
                severity=RuleSeverity.REJECT,
                message="tipo sin placa; RN-07 omitida",
            )
        ctx_placa = _as_text(context.placa)
        if ctx_placa is None:
            return RuleDetail(
                rule_id="RN-07",
                passed=False,
                severity=RuleSeverity.MANUAL,
                message=(
                    "contexto de placa no recibido; "
                    "no se pudo validar coincidencia"
                ),
            )
        doc_placa = _concept_valor(normalized, "placa")
        if doc_placa is None or _norm_id(doc_placa) != _norm_id(ctx_placa):
            return RuleDetail(
                rule_id="RN-07",
                passed=False,
                severity=RuleSeverity.REJECT,
                message="placa no coincide con el vehículo registrado",
            )
        return RuleDetail(
            rule_id="RN-07",
            passed=True,
            severity=RuleSeverity.REJECT,
            message="placa coincide con contexto",
        )

    def _rn08_aseguradora(
        self,
        campos_extraidos: Mapping[str, CampoExtraido],
        rules: Mapping[str, Any],
    ) -> RuleDetail:
        """RN-08: aseguradora autorizada por SBP (catálogo JSONB).

        Si ``aseguradoras_autorizadas`` está vacío, se omite la regla y se
        emite ``log.warning`` (cualquier aseguradora se acepta temporalmente).
        """
        raw_list = rules.get("aseguradoras_autorizadas", [])
        autorizadas: list[str] = []
        if isinstance(raw_list, Sequence) and not isinstance(raw_list, (str, bytes)):
            for item in raw_list:
                text = _as_text(item)
                if text is not None:
                    autorizadas.append(text)

        if not autorizadas:
            logger.warning(
                "rn08_catalogo_aseguradoras_vacio",
                extra={
                    "context": {
                        "rule_id": "RN-08",
                        "efecto": "skip",
                        "detalle": (
                            "aseguradoras_autorizadas vacío; "
                            "cualquier aseguradora se acepta sin validar"
                        ),
                    }
                },
            )
            return RuleDetail(
                rule_id="RN-08",
                passed=True,
                severity=RuleSeverity.REJECT,
                message="catálogo de aseguradoras vacío; regla omitida",
            )

        aseguradora = _raw_field_valor(
            campos_extraidos,
            "aseguradora",
            "compania",
            "compañia",
            "empresa_aseguradora",
        )
        permitidas = {_norm_name(a) for a in autorizadas}
        if aseguradora is None or _norm_name(aseguradora) not in permitidas:
            return RuleDetail(
                rule_id="RN-08",
                passed=False,
                severity=RuleSeverity.REJECT,
                message="aseguradora no autorizada por la SBP",
            )
        return RuleDetail(
            rule_id="RN-08",
            passed=True,
            severity=RuleSeverity.REJECT,
            message="aseguradora autorizada",
        )

    def _rn09_resultado(
        self,
        campos_extraidos: Mapping[str, CampoExtraido],
        rules: Mapping[str, Any],
    ) -> RuleDetail:
        """RN-09: resultado del revisado técnico aprobado."""
        raw_list = rules.get("resultados_validos", _DEFAULT_RESULTADOS_REVISADO)
        validos = {
            _norm_name(str(r))
            for r in raw_list
            if _as_text(r) is not None
        }
        resultado = _raw_field_valor(campos_extraidos, "resultado", "dictamen")
        if resultado is None or _norm_name(resultado) not in validos:
            return RuleDetail(
                rule_id="RN-09",
                passed=False,
                severity=RuleSeverity.REJECT,
                message="resultado de revisado técnico no aprobado",
            )
        return RuleDetail(
            rule_id="RN-09",
            passed=True,
            severity=RuleSeverity.REJECT,
            message="resultado de revisado técnico válido",
        )

    def _rn10_cedula(
        self,
        normalized: Mapping[str, NormalizedField | None],
        context: CarrierContext,
        rules: Mapping[str, Any],
    ) -> RuleDetail:
        """RN-10: cédula del CRCT coincide con el transportista."""
        return self._rn04_match_titular(
            normalized,
            CarrierContext(cedula=context.cedula, nombre=None, placa=None),
            rules,
            rule_id="RN-10",
        )

    def _rn11_mayoria_edad(
        self,
        campos_extraidos: Mapping[str, CampoExtraido],
        rules: Mapping[str, Any],
        today: date,
    ) -> RuleDetail:
        """RN-11: titular mayor de edad; ilegible → MANUAL (no REJECT).

        Campo no legible se trata como mala calidad de imagen, no como
        documento inválido: escala a revisión humana (RF-21).
        """
        raw_edad = rules.get("edad_minima", _DEFAULT_EDAD_MINIMA)
        try:
            edad_minima = int(raw_edad)
        except (TypeError, ValueError):
            edad_minima = _DEFAULT_EDAD_MINIMA

        birth_raw = _raw_field_valor(
            campos_extraidos,
            "fecha_nacimiento",
            "fecha_nac",
            "nacimiento",
        )
        if birth_raw is None:
            return RuleDetail(
                rule_id="RN-11",
                passed=False,
                severity=RuleSeverity.MANUAL,
                message=(
                    "fecha_nacimiento no legible; requiere revisión manual"
                ),
            )
        try:
            birth = parse_panama_date(birth_raw)
        except InvalidDateFormatError:
            return RuleDetail(
                rule_id="RN-11",
                passed=False,
                severity=RuleSeverity.MANUAL,
                message=(
                    "fecha_nacimiento no parseable; requiere revisión manual"
                ),
            )

        age = _age_years(birth, today)
        if age < edad_minima:
            return RuleDetail(
                rule_id="RN-11",
                passed=False,
                severity=RuleSeverity.REJECT,
                message=f"titular menor de edad ({age} años)",
            )
        return RuleDetail(
            rule_id="RN-11",
            passed=True,
            severity=RuleSeverity.MANUAL,
            message="titular mayor de edad",
        )

    def _rn12_proximidad(
        self,
        normalized: Mapping[str, NormalizedField | None],
        rules: Mapping[str, Any],
        today: date,
    ) -> RuleDetail | None:
        """RN-12: alerta si vence en menos de N días (no rechazo)."""
        raw_dias = rules.get("dias_alerta_proximidad", _DEFAULT_DIAS_ALERTA)
        try:
            dias_alerta = int(raw_dias)
        except (TypeError, ValueError):
            dias_alerta = _DEFAULT_DIAS_ALERTA

        expiry = _parse_expiry(normalized)
        if expiry is None:
            return None
        days = days_until_expiry(expiry, today=today)
        if 0 <= days < dias_alerta:
            return RuleDetail(
                rule_id="RN-12",
                passed=False,
                severity=RuleSeverity.ALERT,
                message=f"documento vence en {days} día(s)",
            )
        return RuleDetail(
            rule_id="RN-12",
            passed=True,
            severity=RuleSeverity.ALERT,
            message="sin alerta de proximidad de vencimiento",
        )
