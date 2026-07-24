"""Handler Lambda del worker de verificación documental (M-ORQ / P4.2).

Orquesta el pipeline SQS → S3 → OCR → normalizar → rules → scoring →
persistencia → SNS. Sin lógica de negocio (vive en services).

Política de entrega (at-least-once, no exactly-once):
    - OCR/rules/scoring/INSERT se omiten si ya existe Historial con el
      mismo documento_id + prompt_hash + version_extraccion.
    - El resultado SNS (paso 9) se publica SIEMPRE; Panalogix deduplica.
      No hay campo ``enviada_en`` en historial: un
      ``NonRetryableNotificationError`` tras persistir deja el documento
      sin notificación automática (caso raro de configuración SNS;
      recuperación operativa). Los fallos retryables de SNS sí se cubren
      vía reintento SQS + republicación.
    - La alerta ``revision_manual`` usa ``enviada_en``: INSERT con NULL,
      publish, luego marcar enviada. Si el publish falla, el reintento
      republica porque ``enviada_en`` sigue NULL.
    - ``subir_verified`` + ``actualizar_s3_key_verified`` no son atómicos
      (posible objeto huérfano en verified-docs).
    - Historial con ``modelo_usado="none"`` = fallo no-retryable registrado,
      no una extracción real (relevante para RF-25 / reprocesamiento futuro:
      el lookup idempotente con el mismo prompt_hash bloquearía un retry
      real hasta que RF-25 ignore o caduque esos registros).

Acoplamiento persistencia→notificación en el mismo handler sin outbox
transaccional es aceptado para el MVP.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import ValidationError

from app.models.alerta import Alerta, AlertaCreate
from app.models.documento import Documento
from app.models.enums import DiasAviso, EstadoAlerta, ResultadoVerificacion
from app.models.fields import CampoExtraido, PlaintextPiiPayload
from app.models.historial import Historial, HistorialCreate
from app.models.job import VerificationJobMessage
from app.models.notificacion import AlertaPublicacion, decimal_score_to_str
from app.services.notificacion_mapper import (
    resultado_to_str,
    tipo_documento_publicacion,
    to_resultado_publicacion,
)
from app.repositories.exceptions import (
    DocumentNotFoundError,
    S3ObjectNotFoundError,
)
from app.repositories.patron import PatronRepository
from app.repositories.s3 import S3Repository
from app.repositories.verificacion import VerificacionRepository
from app.services.normalizer import NormalizedField, normalizar
from app.services.ocr import (
    ExtractionContext,
    NonRetryableOcrError,
    OcrService,
)
from app.services.field_applicability import resolve_campos_aplicables
from app.services.pattern_learning import accumulate_pattern
from app.services.rules_engine import CarrierContext, RulesEngine
from app.services.scoring import ScoringService
from app.services.sns import (
    NonRetryableNotificationError,
    NotificationService,
)
from app.utils.dates import InvalidDateFormatError, parse_panama_date
from app.utils.image import CorruptDocumentError, DocumentTooManyPagesError
from app.utils.logging import get_logger
from app.utils.metrics import emit_count
from app.utils.tracing import configure_xray

configure_xray()

logger = get_logger(__name__)

_MODELO_NONE: str = "none"
_EVENT_REVISION_MANUAL: str = "revision_manual"
_ZERO_SCORE: Decimal = Decimal("0.000")
_PII_KEYS: frozenset[str] = frozenset(
    {"cedula", "cédula", "nombre", "nombre_titular", "nombre_completo"}
)

_NON_RETRYABLE_DOC_ERRORS: tuple[type[BaseException], ...] = (
    NonRetryableOcrError,
    CorruptDocumentError,
    DocumentTooManyPagesError,
    S3ObjectNotFoundError,
    DocumentNotFoundError,
)


class VerificationPipeline:
    """Orquestador inyectable del pipeline de verificación."""

    def __init__(
        self,
        *,
        verificacion_repo: VerificacionRepository | None = None,
        s3_repo: S3Repository | None = None,
        ocr: OcrService | None = None,
        rules_engine: RulesEngine | None = None,
        scoring: ScoringService | None = None,
        notifications: NotificationService | None = None,
        patron_repo: PatronRepository | None = None,
        extraction_version: str | None = None,
    ) -> None:
        """Inicializa dependencias (defaults desde settings / constructores)."""
        from app.config import get_worker_settings

        self._repo = verificacion_repo or VerificacionRepository()
        self._s3 = s3_repo or S3Repository()
        self._ocr = ocr or OcrService(
            reglas_resolver=self._repo.obtener_reglas_validacion
        )
        self._rules = rules_engine or RulesEngine()
        self._scoring = scoring or ScoringService()
        self._notifications = notifications or NotificationService()
        self._patron_repo = patron_repo or PatronRepository()
        self._extraction_version = (
            extraction_version
            if extraction_version is not None
            else get_worker_settings().extraction_version
        )

    def process_job(self, message: VerificationJobMessage) -> None:
        """Ejecuta el pipeline para un mensaje SQS ya parseado.

        Args:
            message: Contrato del job (documento_id + contexto).

        Raises:
            RetryableOcrError, RetryableNotificationError, S3RepositoryError,
            RepositoryError: Propagados para reintento SQS / DLQ.
        """
        documento = self._repo.obtener_documento(message.documento_id)
        prompt_hash = self._ocr.prompt_hash
        version = self._extraction_version

        existing = self._repo.obtener_extraccion_idempotente(
            documento.id,
            prompt_hash,
            version,
        )
        idempotent_hit = existing is not None
        raw_bytes: bytes | None = None

        if existing is not None:
            historial = existing
            logger.info(
                "verificacion_idempotent_hit",
                extra={
                    "context": {
                        "documento_id": str(documento.id),
                        "historial_id": str(historial.id),
                        "prompt_hash": prompt_hash,
                        "version_extraccion": version,
                        "modelo_usado": historial.modelo_usado,
                        "idempotent_hit": True,
                    }
                },
            )
        else:
            raw_bytes = self._s3.descargar_raw(documento.s3_key_raw)
            historial = self._run_extraction_pipeline(
                documento=documento,
                message=message,
                raw_bytes=raw_bytes,
                prompt_hash=prompt_hash,
                version=version,
            )

        if (
            resultado_to_str(historial.resultado)
            == ResultadoVerificacion.APROBADO.value
            and not idempotent_hit
            and raw_bytes is not None
        ):
            self._copy_verified(documento, raw_bytes)

        self._publish_resultado(documento, historial)

        if (
            resultado_to_str(historial.resultado)
            == ResultadoVerificacion.REVISION_MANUAL.value
        ):
            self._publish_revision_manual_alerta(documento, historial)

    def handle_non_retryable_document_failure(
        self,
        message: VerificationJobMessage,
        *,
        error: BaseException,
    ) -> None:
        """Registra fallo no-retryable como REVISION_MANUAL y notifica.

        Args:
            message: Job original (debe tener documento_id válido).
            error: Excepción capturada (solo para logging).
        """
        logger.error(
            "verificacion_non_retryable",
            extra={
                "context": {
                    "documento_id": str(message.documento_id),
                    "error": type(error).__name__,
                    "detalle": str(error)[:200],
                }
            },
        )
        documento = self._repo.obtener_documento(message.documento_id)
        prompt_hash = self._ocr.prompt_hash
        version = self._extraction_version

        existing = self._repo.obtener_extraccion_idempotente(
            documento.id,
            prompt_hash,
            version,
        )
        if existing is not None:
            historial = existing
        else:
            tipo = (message.tipo_declarado or "desconocido").strip() or "desconocido"
            historial = self._repo.registrar_extraccion(
                HistorialCreate(
                    documento_id=documento.id,
                    tipo_detectado=tipo[:40],
                    campos_extraidos={},
                    resultado=ResultadoVerificacion.REVISION_MANUAL,
                    score_lectura=_ZERO_SCORE,
                    score_autenticidad=_ZERO_SCORE,
                    modelo_usado=_MODELO_NONE,
                    version_extraccion=version,
                    prompt_hash=prompt_hash,
                    costo_api=Decimal("0.000000"),
                    fecha_vencimiento=None,
                )
            )
            emit_count(
                "VerificacionesPorResultado",
                dimensions={
                    "tipo_documento": tipo[:40],
                    "resultado": ResultadoVerificacion.REVISION_MANUAL.value,
                },
            )
            logger.info(
                "verificacion_historial_minimo",
                extra={
                    "context": {
                        "documento_id": str(documento.id),
                        "historial_id": str(historial.id),
                        "modelo_usado": _MODELO_NONE,
                    }
                },
            )

        self._publish_resultado(documento, historial)
        self._publish_revision_manual_alerta(documento, historial)

    def _run_extraction_pipeline(
        self,
        *,
        documento: Documento,
        message: VerificationJobMessage,
        raw_bytes: bytes,
        prompt_hash: str,
        version: str,
    ) -> Historial:
        """OCR → normalize → rules → score → persist."""
        extraction_ctx = ExtractionContext(
            cedula_registrada=message.cedula_registrada,
            placa_registrada=message.placa_registrada,
            nombre_registrado=message.nombre_registrado,
            tipo_declarado=message.tipo_declarado or documento.tipo_documento,
        )
        extraction = self._ocr.extract(raw_bytes, extraction_ctx)
        campos = extraction.campos
        normalized = normalizar(campos)
        carrier = CarrierContext(
            cedula=message.cedula_registrada,
            placa=message.placa_registrada,
            nombre=message.nombre_registrado,
        )
        reglas = self._repo.obtener_reglas_validacion(extraction.tipo_detectado)
        rules = self._rules.evaluate(
            campos_extraidos=campos,
            normalized=normalized,
            context=carrier,
            tipo_detectado=extraction.tipo_detectado,
            reglas_validacion=reglas,
        )
        aplicables = resolve_campos_aplicables(
            extraction.tipo_detectado,
            reglas,
        )
        scoring = self._scoring.evaluate(
            rules,
            campos,
            campos_aplicables=aplicables,
            anomalias=extraction.anomalias,
        )
        campos_limpios, pii = _split_pii(campos)
        fecha_venc = _fecha_vencimiento_from_normalized(normalized)

        historial = self._repo.registrar_extraccion(
            HistorialCreate(
                documento_id=documento.id,
                tipo_detectado=extraction.tipo_detectado,
                campos_extraidos=campos_limpios,
                resultado=scoring.resultado,
                score_lectura=scoring.score_lectura,
                score_autenticidad=scoring.score_autenticidad,
                modelo_usado=extraction.modelo_usado,
                version_extraccion=version,
                prompt_hash=prompt_hash,
                costo_api=extraction.costo_api,
                fecha_vencimiento=fecha_venc,
            ),
            pii_plaintext=pii,
        )
        emit_count(
            "VerificacionesPorResultado",
            dimensions={
                "tipo_documento": extraction.tipo_detectado,
                "resultado": resultado_to_str(scoring.resultado),
            },
        )
        accumulate_pattern(
            patron_repo=self._patron_repo,
            tipo_detectado=extraction.tipo_detectado,
            campos=campos,
            score_lectura=scoring.score_lectura,
            entidad_emisora=extraction.entidad_emisora,
            tipo_declarado=message.tipo_declarado,
        )
        logger.info(
            "verificacion_extraccion_ok",
            extra={
                "context": {
                    "documento_id": str(documento.id),
                    "historial_id": str(historial.id),
                    "resultado": resultado_to_str(scoring.resultado),
                    "prompt_hash": prompt_hash,
                    "version_extraccion": version,
                    "idempotent_hit": False,
                }
            },
        )
        return historial

    def _copy_verified(self, documento: Documento, raw_bytes: bytes) -> None:
        """Copia a verified-docs y actualiza BD (no atómico)."""
        key = documento.s3_key_raw
        self._s3.subir_verified(key, raw_bytes)
        self._repo.actualizar_s3_key_verified(documento.id, key)
        logger.info(
            "verificacion_verified_ok",
            extra={
                "context": {
                    "documento_id": str(documento.id),
                    "s3_key_verified": key,
                }
            },
        )

    def _publish_resultado(
        self,
        documento: Documento,
        historial: Historial,
    ) -> None:
        """Publica ResultadoPublicacion (siempre; at-least-once)."""
        payload = to_resultado_publicacion(documento, historial)
        message_id = self._notifications.publicar_resultado(payload)
        logger.info(
            "verificacion_sns_resultado",
            extra={
                "context": {
                    "documento_id": str(documento.id),
                    "historial_id": str(historial.id),
                    "resultado": resultado_to_str(historial.resultado),
                    "sns_message_id": message_id,
                }
            },
        )

    def _publish_revision_manual_alerta(
        self,
        documento: Documento,
        historial: Historial,
    ) -> None:
        """Alerta revision_manual gateada por enviada_en."""
        inserted = self._repo.try_registrar_alerta(
            AlertaCreate(
                historial_id=historial.id,
                dias_aviso=DiasAviso.ZERO,
                estado=EstadoAlerta.PENDIENTE,
            )
        )
        alerta: Alerta | None = inserted
        if alerta is None:
            alerta = self._repo.obtener_alerta(historial.id, int(DiasAviso.ZERO))

        if alerta is None:
            logger.error(
                "verificacion_alerta_no_encontrada",
                extra={
                    "context": {
                        "historial_id": str(historial.id),
                        "dias_aviso": 0,
                    }
                },
            )
            return

        if alerta.enviada_en is not None:
            logger.info(
                "verificacion_alerta_ya_enviada",
                extra={
                    "context": {
                        "historial_id": str(historial.id),
                        "alerta_id": str(alerta.id),
                        "alerta_enviada": True,
                    }
                },
            )
            return

        payload = AlertaPublicacion(
            transportista_id=documento.transportista_id,
            tipo_documento=tipo_documento_publicacion(documento, historial),
            resultado=resultado_to_str(historial.resultado),
            score_lectura=decimal_score_to_str(historial.score_lectura),
            score_autenticidad=decimal_score_to_str(historial.score_autenticidad),
            fecha_vencimiento=historial.fecha_vencimiento,
        )
        message_id = self._notifications.publicar_alerta(
            payload,
            dias_aviso=0,
            event_type=_EVENT_REVISION_MANUAL,
        )
        self._repo.marcar_alerta_enviada(alerta.id)
        logger.info(
            "verificacion_sns_alerta",
            extra={
                "context": {
                    "documento_id": str(documento.id),
                    "historial_id": str(historial.id),
                    "alerta_id": str(alerta.id),
                    "sns_message_id": message_id,
                    "event_type": _EVENT_REVISION_MANUAL,
                    "alerta_enviada": True,
                }
            },
        )


def _split_pii(
    campos: dict[str, CampoExtraido],
) -> tuple[dict[str, CampoExtraido], PlaintextPiiPayload | None]:
    """Separa PII de campos_extraidos (prohibido en claro en JSONB)."""
    limpios: dict[str, CampoExtraido] = {}
    cedula_val: str | None = None
    nombre_val: str | None = None

    for key, campo in campos.items():
        norm = key.casefold().strip()
        if norm in _PII_KEYS or norm.replace(" ", "_") in _PII_KEYS:
            text = None if campo.valor is None else str(campo.valor).strip()
            if text:
                if "cedula" in norm or "cédula" in norm:
                    cedula_val = text
                elif "nombre" in norm:
                    nombre_val = text
            continue
        limpios[key] = campo

    pii: PlaintextPiiPayload | None = None
    if cedula_val and nombre_val:
        try:
            pii = PlaintextPiiPayload(cedula=cedula_val, nombre_titular=nombre_val)
        except ValidationError:
            logger.warning(
                "verificacion_pii_invalida",
                extra={"context": {"detalle": "cedula/nombre no pasan validador"}},
            )
    return limpios, pii


def _fecha_vencimiento_from_normalized(
    normalized: dict[str, NormalizedField | None],
) -> date | None:
    """Extrae fecha_vencimiento canónica parseable, o None."""
    field = normalized.get("fecha_vencimiento")
    if field is None or field.valor is None:
        return None
    text = str(field.valor).strip()
    if not text:
        return None
    try:
        return parse_panama_date(text)
    except InvalidDateFormatError:
        return None


def _parse_record_body(raw_body: str) -> VerificationJobMessage:
    """Deserializa el body SQS a VerificationJobMessage."""
    data = json.loads(raw_body)
    if not isinstance(data, dict):
        raise ValueError("body SQS debe ser un objeto JSON")
    return VerificationJobMessage.model_validate(data)


def handler(event: dict[str, Any], context: object) -> dict[str, Any]:
    """Punto de entrada Lambda (event source mapping SQS).

    Args:
        event: Evento SQS con ``Records``.
        context: Contexto Lambda (no usado).

    Returns:
        Dict vacío en éxito de batch (mensajes ack implícito salvo excepción).
    """
    del context  # API Lambda; no usado en MVP.
    pipeline = VerificationPipeline()
    records = event.get("Records") or []

    for record in records:
        message_id = record.get("messageId")
        try:
            body = record.get("body") or ""
            message = _parse_record_body(body)
        except (ValidationError, json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.error(
                "verificacion_mensaje_invalido",
                extra={
                    "context": {
                        "sqs_message_id": message_id,
                        "error": type(exc).__name__,
                    }
                },
            )
            continue

        try:
            pipeline.process_job(message)
        except _NON_RETRYABLE_DOC_ERRORS as exc:
            try:
                pipeline.handle_non_retryable_document_failure(message, error=exc)
            except NonRetryableNotificationError as notify_exc:
                logger.error(
                    "verificacion_sns_non_retryable",
                    extra={
                        "context": {
                            "documento_id": str(message.documento_id),
                            "error": type(notify_exc).__name__,
                        }
                    },
                )
            except DocumentNotFoundError as missing:
                logger.error(
                    "verificacion_documento_ausente",
                    extra={
                        "context": {
                            "documento_id": str(message.documento_id),
                            "error": type(missing).__name__,
                        }
                    },
                )
        except NonRetryableNotificationError as exc:
            logger.error(
                "verificacion_sns_non_retryable",
                extra={
                    "context": {
                        "documento_id": str(message.documento_id),
                        "error": type(exc).__name__,
                    }
                },
            )
        # RetryableOcrError, RetryableNotificationError, S3RepositoryError,
        # RepositoryError: se propagan → SQS reintenta / DLQ.

    return {}
