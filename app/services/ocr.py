"""Servicio de extracción semántica de documentos vía Claude.

Aplica la estrategia híbrida Haiku → Sonnet según umbral de confianza.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from collections.abc import Callable, Mapping
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any

import anthropic
from anthropic import APIConnectionError, APIStatusError, APITimeoutError, RateLimitError
from pydantic import BaseModel, ConfigDict, Field

from app.models.fields import CampoExtraido, ScoreDecimal
from app.services.field_applicability import (
    min_confidence_aplicables,
    resolve_campos_aplicables,
)
from app.utils.image import (
    CorruptDocumentError,
    DocumentTooManyPagesError,
    prepare_document_images,
)
from app.utils.logging import get_logger

logger = get_logger(__name__)

_PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"
_EXTRACTION_TEMPLATE = "extraction_universal.txt"
_QUANTIZE = Decimal("0.001")

# Tarifas estimadas USD por millón de tokens (costo operativo / Grafana).
_COST_PER_MTOK: dict[str, tuple[Decimal, Decimal]] = {
    "haiku": (Decimal("0.80"), Decimal("4.00")),
    "sonnet": (Decimal("3.00"), Decimal("15.00")),
}

_KNOWN_TIPOS = frozenset(
    {
        "licencia",
        "cedula",
        "soat",
        "revisado",
        "crct",
        "permiso_pesos",
        "desconocido",
    }
)


class OcrError(Exception):
    """Error base del servicio OCR."""


class RetryableOcrError(OcrError):
    """Error reintentable (RateLimit / 5xx) — SQS debe reintentar."""


class NonRetryableOcrError(OcrError):
    """Error no reintentable (4xx / documento inválido)."""


class ExtractionContext(BaseModel):
    """Contexto de validación inyectado por Panalogix (no acopla BD)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    cedula_registrada: str | None = None
    placa_registrada: str | None = None
    nombre_registrado: str | None = None
    tipo_declarado: str | None = None


class ExtractionResult(BaseModel):
    """Resultado de la extracción semántica híbrida."""

    model_config = ConfigDict(str_strip_whitespace=True)

    campos: dict[str, CampoExtraido]
    tipo_detectado: str = Field(..., max_length=40)
    modelo_usado: str = Field(..., max_length=30)
    costo_api: Decimal = Field(..., max_digits=10, decimal_places=6)
    anomalias: list[str] = Field(default_factory=list)
    prompt_hash: str = Field(..., max_length=64)
    confianza_minima: ScoreDecimal
    entidad_emisora: str | None = None


def _to_score_decimal(raw: object) -> Decimal:
    """Convierte confianza a Decimal sin pasar por float.

    Args:
        raw: Valor del modelo (str, int o Decimal).

    Returns:
        Decimal cuantizado a 3 decimales en [0, 1].
    """
    if isinstance(raw, bool):
        raise NonRetryableOcrError("confianza inválida (bool)")
    if isinstance(raw, Decimal):
        value = raw
    elif isinstance(raw, int):
        value = Decimal(raw)
    elif isinstance(raw, str):
        try:
            value = Decimal(raw.strip())
        except InvalidOperation as exc:
            raise NonRetryableOcrError(f"confianza no numérica: {raw!r}") from exc
    elif isinstance(raw, float):
        # Evitar Decimal(float); serializar vía str.
        value = Decimal(str(raw))
    else:
        raise NonRetryableOcrError(f"tipo de confianza no soportado: {type(raw)!r}")

    value = value.quantize(_QUANTIZE, rounding=ROUND_HALF_UP)
    if value < Decimal("0") or value > Decimal("1"):
        raise NonRetryableOcrError(f"confianza fuera de rango: {value}")
    return value


def _estimate_cost(model: str, input_tokens: int, output_tokens: int) -> Decimal:
    """Estima costo USD a partir del uso de tokens."""
    family = "sonnet" if "sonnet" in model.lower() else "haiku"
    in_rate, out_rate = _COST_PER_MTOK[family]
    cost = (Decimal(input_tokens) / Decimal(1_000_000)) * in_rate + (
        Decimal(output_tokens) / Decimal(1_000_000)
    ) * out_rate
    return cost.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


def _load_prompt_template() -> tuple[str, str]:
    """Carga el template universal y calcula prompt_hash.

    Returns:
        Par ``(contenido, sha256_hex)``.
    """
    path = _PROMPTS_DIR / _EXTRACTION_TEMPLATE
    content = path.read_text(encoding="utf-8")
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return content, digest


def _render_prompt(template: str, context: ExtractionContext) -> str:
    """Sustituye el bloque de contexto en el template."""
    lines: list[str] = []
    if context.cedula_registrada:
        lines.append(f"- cedula_registrada: {context.cedula_registrada}")
    if context.placa_registrada:
        lines.append(f"- placa_registrada: {context.placa_registrada}")
    if context.nombre_registrado:
        lines.append(f"- nombre_registrado: {context.nombre_registrado}")
    if context.tipo_declarado:
        lines.append(f"- tipo_declarado: {context.tipo_declarado}")
    block = "\n".join(lines) if lines else "- (sin contexto adicional)"
    return template.replace("{{CONTEXT_BLOCK}}", block)


def _extract_json_object(text: str) -> dict[str, Any]:
    """Parsea el primer objeto JSON del texto del modelo."""
    text = text.strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        raise NonRetryableOcrError("la respuesta del modelo no contiene JSON")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise NonRetryableOcrError("JSON de extracción inválido") from exc
    if not isinstance(data, dict):
        raise NonRetryableOcrError("JSON de extracción no es un objeto")
    return data


def _parse_extraction_payload(
    data: dict[str, Any],
) -> tuple[dict[str, CampoExtraido], str, list[str], str | None]:
    """Valida y tipa la carga útil del modelo."""
    tipo = str(data.get("tipo_detectado") or "desconocido").strip().lower()
    if tipo not in _KNOWN_TIPOS:
        tipo = "desconocido"

    raw_campos = data.get("campos") or {}
    if not isinstance(raw_campos, dict):
        raise NonRetryableOcrError("campos debe ser un objeto")

    campos: dict[str, CampoExtraido] = {}
    for key, payload in raw_campos.items():
        if not isinstance(payload, dict):
            continue
        confianza = _to_score_decimal(payload.get("confianza", "0.000"))
        campos[str(key)] = CampoExtraido(
            valor=payload.get("valor"),
            confianza=confianza,
        )

    anomalias_raw = data.get("anomalias") or []
    if not isinstance(anomalias_raw, list):
        raise NonRetryableOcrError("anomalias debe ser una lista")
    anomalias = [str(item) for item in anomalias_raw]

    entidad_emisora: str | None = None
    raw_emisor = data.get("entidad_emisora")
    if isinstance(raw_emisor, str):
        stripped = raw_emisor.strip()
        if stripped:
            entidad_emisora = stripped

    return campos, tipo, anomalias, entidad_emisora


class OcrService:
    """Extracción semántica universal con estrategia híbrida Haiku/Sonnet.

    ``confianza_minima`` se calcula solo sobre ``campos_aplicables`` del
    tipo detectado (JSONB / defaults). Campos no aplicables (p. ej. placa
    en licencia) no disparan escalamiento. Campos aplicables ilegibles sí
    bajan el mínimo y pueden disparar **una** escalada Haiku→Sonnet; no
    hay segundo escalate si tras Sonnet sigue bajo.

    Args:
        client: Cliente Anthropic inyectable (tests).
        prompt_template: Texto del template (default: archivo en prompts/).
        reglas_resolver: Callable ``tipo → reglas_validacion`` (p. ej.
            ``VerificacionRepository.obtener_reglas_validacion``).
    """

    def __init__(
        self,
        *,
        client: anthropic.Anthropic | None = None,
        prompt_template: str | None = None,
        reglas_resolver: Callable[[str], Mapping[str, Any]] | None = None,
    ) -> None:
        """Inicializa el servicio cargando prompt y configuración."""
        from app.config import get_worker_settings

        self._settings = get_worker_settings()
        if prompt_template is None:
            template, prompt_hash = _load_prompt_template()
        else:
            template = prompt_template
            prompt_hash = hashlib.sha256(template.encode("utf-8")).hexdigest()
        self._template = template
        self._prompt_hash = prompt_hash
        self._client = client or anthropic.Anthropic(
            api_key=self._settings.anthropic_api_key
        )
        self._reglas_resolver = reglas_resolver

    @property
    def prompt_hash(self) -> str:
        """SHA-256 del template de extracción (sin contexto inyectado)."""
        return self._prompt_hash

    def _confianza_minima(
        self,
        campos: dict[str, CampoExtraido],
        tipo: str,
    ) -> Decimal:
        """Mínima confianza sobre campos aplicables al tipo detectado."""
        reglas: Mapping[str, Any] | None = None
        if self._reglas_resolver is not None:
            reglas = self._reglas_resolver(tipo)
        aplicables = resolve_campos_aplicables(tipo, reglas)
        return min_confidence_aplicables(campos, aplicables)

    def extract(self, document_bytes: bytes, context: ExtractionContext) -> ExtractionResult:
        """Extrae campos con estrategia híbrida.

        Args:
            document_bytes: JPEG, PNG o PDF del documento.
            context: Contexto del transportista enviado por Panalogix.

        Returns:
            Resultado tipado con ``CampoExtraido`` / ``Decimal``.

        Raises:
            RetryableOcrError: Rate limit o errores 5xx (SQS reintenta).
            NonRetryableOcrError: 4xx u otros fallos definitivos.
            CorruptDocumentError: Documento ilegible.
            DocumentTooManyPagesError: PDF sobre el límite de páginas.
        """
        images = prepare_document_images(document_bytes)
        prompt = _render_prompt(self._template, context)

        primary = self._settings.primary_model
        threshold = Decimal(str(self._settings.confidence_threshold))

        first = self._call_model(model=primary, images=images, prompt=prompt)
        campos, tipo, anomalias, entidad_emisora = first["parsed"]
        costo = first["cost"]
        modelo_usado = primary

        min_conf = self._confianza_minima(campos, tipo)

        if min_conf < threshold:
            fallback = self._settings.fallback_model
            logger.info(
                "ocr_escalando_fallback",
                extra={
                    "context": {
                        "confianza_minima": str(min_conf),
                        "umbral": str(threshold),
                        "modelo": fallback,
                        "tipo_detectado": tipo,
                    }
                },
            )
            second = self._call_model(model=fallback, images=images, prompt=prompt)
            campos, tipo, anomalias, entidad_emisora = second["parsed"]
            costo += second["cost"]
            modelo_usado = fallback
            # Recalcula para el resultado final; no hay segundo escalate.
            min_conf = self._confianza_minima(campos, tipo)

        result = ExtractionResult(
            campos=campos,
            tipo_detectado=tipo,
            modelo_usado=modelo_usado,
            costo_api=costo,
            anomalias=anomalias,
            prompt_hash=self._prompt_hash,
            confianza_minima=min_conf,
            entidad_emisora=entidad_emisora,
        )
        logger.info(
            "ocr_extract_ok",
            extra={
                "context": {
                    "modelo_usado": modelo_usado,
                    "tipo_detectado": tipo,
                    "costo_api": str(costo),
                    "prompt_hash": self._prompt_hash,
                    "paginas": len(images),
                    "confianza_minima": str(min_conf),
                }
            },
        )
        return result

    def _call_model(
        self,
        *,
        model: str,
        images: list[bytes],
        prompt: str,
    ) -> dict[str, Any]:
        """Invoca Claude Vision con una o más páginas JPEG."""
        content: list[dict[str, Any]] = []
        for image_bytes in images:
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": base64.b64encode(image_bytes).decode("ascii"),
                    },
                }
            )
        content.append({"type": "text", "text": prompt})

        try:
            response = self._client.messages.create(
                model=model,
                max_tokens=4096,
                temperature=0,
                messages=[{"role": "user", "content": content}],
            )
        except RateLimitError as exc:
            raise RetryableOcrError("rate limit de Anthropic") from exc
        except (APIConnectionError, APITimeoutError) as exc:
            raise RetryableOcrError("error de red/timeout con Anthropic") from exc
        except APIStatusError as exc:
            status = getattr(exc, "status_code", None) or 0
            if status >= 500:
                raise RetryableOcrError(f"Anthropic {status}") from exc
            raise NonRetryableOcrError(f"Anthropic client error {status}") from exc
        except anthropic.APIError as exc:
            raise NonRetryableOcrError("error de API Anthropic") from exc

        text_parts = [
            block.text
            for block in response.content
            if getattr(block, "type", None) == "text" and hasattr(block, "text")
        ]
        raw_text = "\n".join(text_parts).strip()
        payload = _extract_json_object(raw_text)
        parsed = _parse_extraction_payload(payload)

        usage = response.usage
        input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
        cost = _estimate_cost(model, input_tokens, output_tokens)

        logger.info(
            "ocr_model_call",
            extra={
                "context": {
                    "model": model,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "costo_api": str(cost),
                }
            },
        )
        return {"parsed": parsed, "cost": cost}


# Reexportar errores de imagen para el worker/SQS.
__all__ = [
    "CorruptDocumentError",
    "DocumentTooManyPagesError",
    "ExtractionContext",
    "ExtractionResult",
    "NonRetryableOcrError",
    "OcrError",
    "OcrService",
    "RetryableOcrError",
]
