#!/usr/bin/env python3
"""Smoke test E2E local del pipeline de verificación (sin S3/SNS reales).

Llamadas REALES a servicios externos en este script:
  - Anthropic (Claude) — la extracción OCR es real.
  - AWS KMS — el cifrado de campos PII (cédula, nombre) vía
    VerificacionRepository.registrar_extraccion es real; usa las
    credenciales del perfil AWS local y la clave en KMS_KEY_ID.

Llamadas SIMULADAS (no tocan AWS real):
  - S3 — se lee el archivo del disco local en vez de descargar de un bucket.
  - SNS — el resultado se imprime en consola en vez de publicarse.

Uso::

    PYTHONPATH=. python scripts/smoke_test_local.py --imagen ruta/doc.jpg

Prerrequisitos — obligatorios con valor REAL:
  - DATABASE_URL       → Postgres local (localhost:5432)
  - ANTHROPIC_API_KEY  → clave real
  - KMS_KEY_ID         → valor real (p. ej. alias/panalogix-pii), no placeholder
  - AWS_REGION         → valor real (p. ej. us-east-1), no placeholder
  - Credenciales AWS locales válidas para kms:Encrypt / GenerateDataKey
  - Migraciones 001–003 aplicadas; schema verificaciones

Prerrequisitos — pueden ser PLACEHOLDER (el stub S3/SNS no los consulta):
  - AWS_S3_RAW_BUCKET
  - AWS_S3_VERIFIED_BUCKET
  - AWS_SQS_QUEUE_URL
  - AWS_SNS_TOPIC_ARN

Resto de WorkerSettings (MODELO_*, umbrales, VERSION_EXTRACCION, etc.)
según el .env de desarrollo habitual.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from app.config import get_worker_settings
from app.handlers.lambda_handler import VerificationPipeline
from app.models.documento import DocumentoCreate
from app.models.job import VerificationJobMessage
from app.models.notificacion import AlertaPublicacion, ResultadoPublicacion
from app.repositories.verificacion import VerificacionRepository
from app.services.ocr import ExtractionContext, ExtractionResult, OcrService
from app.services.rules_engine import RulesEngine, RulesEvaluation
from app.services.scoring import ScoringService


class LocalFileS3Repository:
    """Stub S3: sirve bytes de un archivo local; verified es no-op."""

    def __init__(self, local_bytes: bytes) -> None:
        """Guarda el contenido que ``descargar_raw`` devolverá siempre."""
        self._bytes = local_bytes

    def descargar_raw(self, key: str) -> bytes:
        """Devuelve los bytes locales (ignora la key salvo para log)."""
        print(f"[S3 stub] descargar_raw key={key!r} → {len(self._bytes)} bytes locales")
        return self._bytes

    def subir_verified(
        self,
        key: str,
        body: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        """No sube a AWS; solo registra en consola."""
        del content_type
        print(
            f"[S3 stub] subir_verified key={key!r} "
            f"bytes={len(body)} (no-op, sin put a AWS)"
        )
        return key


class ConsoleNotificationService:
    """Stub SNS: imprime el payload JSON; no llama a boto3."""

    def publicar_resultado(self, payload: ResultadoPublicacion) -> str:
        """Imprime el contrato de resultado como si fuera Publish SNS."""
        body = payload.model_dump(mode="json")
        message_id = f"console-resultado-{uuid4()}"
        print("[SNS stub] publicar_resultado")
        print(json.dumps(body, ensure_ascii=False, indent=2))
        print(f"[SNS stub] message_id={message_id}")
        return message_id

    def publicar_alerta(
        self,
        payload: AlertaPublicacion,
        *,
        dias_aviso: int,
        event_type: str,
    ) -> str:
        """Imprime el contrato de alerta como si fuera Publish SNS."""
        body = {
            **payload.model_dump(mode="json"),
            "dias_aviso": dias_aviso,
            "event_type": event_type,
        }
        message_id = f"console-alerta-{uuid4()}"
        print("[SNS stub] publicar_alerta")
        print(json.dumps(body, ensure_ascii=False, indent=2))
        print(f"[SNS stub] message_id={message_id}")
        return message_id


class LoggingOcrService:
    """Wrapper sobre OcrService real que imprime el resultado de extracción."""

    def __init__(self, inner: OcrService) -> None:
        """Delega en el OCR real de Anthropic."""
        self._inner = inner

    @property
    def prompt_hash(self) -> str:
        """SHA-256 del template (igual que el servicio real)."""
        return self._inner.prompt_hash

    def extract(
        self,
        document_bytes: bytes,
        context: ExtractionContext,
    ) -> ExtractionResult:
        """Extrae con Claude y muestra un resumen en consola."""
        print(
            f"[OCR] extrayendo ({len(document_bytes)} bytes) "
            f"tipo_declarado={context.tipo_declarado!r} …"
        )
        result = self._inner.extract(document_bytes, context)
        campos_preview: dict[str, Any] = {
            k: {
                "valor": v.valor,
                "confianza": str(v.confianza) if v.confianza is not None else None,
            }
            for k, v in result.campos.items()
        }
        print("[OCR] extracción OK")
        print(
            json.dumps(
                {
                    "tipo_detectado": result.tipo_detectado,
                    "modelo_usado": result.modelo_usado,
                    "confianza_minima": str(result.confianza_minima),
                    "costo_api": str(result.costo_api),
                    "anomalias": result.anomalias,
                    "campos": campos_preview,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return result


class CapturingRulesEngine:
    """Wrapper que captura el último RulesEvaluation del process_job real.

    Vigilar en el resumen: si tipo es revisado o permiso_pesos y RN-02
    aparece passed=False, es señal de choque regla-titular vs doc vehículo
    (no corregir RN-02 desde este script).
    """

    def __init__(self, inner: RulesEngine) -> None:
        """Delega en el RulesEngine real."""
        self._inner = inner
        self.last: RulesEvaluation | None = None

    def evaluate(self, **kwargs: Any) -> RulesEvaluation:
        """Ejecuta evaluate y guarda el resultado para el resumen smoke."""
        self.last = self._inner.evaluate(**kwargs)
        return self.last


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """CLI: --imagen obligatorio; contexto de transportista opcional."""
    parser = argparse.ArgumentParser(
        description=(
            "Smoke E2E local: OCR+KMS+Postgres reales; S3/SNS stubs. "
            "Ver docstring del módulo para real vs simulado."
        ),
    )
    parser.add_argument(
        "--imagen",
        required=True,
        help="Ruta local a JPEG/PNG/PDF del documento.",
    )
    parser.add_argument("--cedula", default=None, help="Cédula registrada (contexto).")
    parser.add_argument("--placa", default=None, help="Placa registrada (contexto).")
    parser.add_argument("--nombre", default=None, help="Nombre registrado (contexto).")
    parser.add_argument(
        "--tipo",
        default="cedula",
        help="Tipo de documento declarado (default: cedula).",
    )
    parser.add_argument(
        "--transportista-id",
        default=None,
        help="UUID del transportista (default: UUID aleatorio).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Crea documento, corre VerificationPipeline y imprime resumen."""
    args = _parse_args(argv)
    image_path = Path(args.imagen).expanduser().resolve()
    if not image_path.is_file():
        print(f"error: no existe el archivo: {image_path}", file=sys.stderr)
        return 1

    settings = get_worker_settings()
    raw_bytes = image_path.read_bytes()
    print(f"[smoke] imagen={image_path} ({len(raw_bytes)} bytes)")
    print(f"[smoke] AWS_REGION={settings.aws_region} KMS_KEY_ID={settings.kms_key_id}")
    print(f"[smoke] VERSION_EXTRACCION={settings.extraction_version}")

    transportista_id = (
        UUID(args.transportista_id) if args.transportista_id else uuid4()
    )
    s3_key_raw = f"local/{uuid4()}_{image_path.name}"

    repo = VerificacionRepository()
    documento = repo.crear_documento(
        DocumentoCreate(
            transportista_id=transportista_id,
            tipo_documento=args.tipo,
            s3_key_raw=s3_key_raw,
        )
    )
    print(
        f"[smoke] documento creado id={documento.id} "
        f"transportista_id={documento.transportista_id} "
        f"s3_key_raw={documento.s3_key_raw!r}"
    )

    ocr = LoggingOcrService(
        OcrService(reglas_resolver=repo.obtener_reglas_validacion)
    )
    rules_capture = CapturingRulesEngine(RulesEngine())
    pipeline = VerificationPipeline(
        verificacion_repo=repo,
        s3_repo=LocalFileS3Repository(raw_bytes),  # type: ignore[arg-type]
        ocr=ocr,  # type: ignore[arg-type]
        rules_engine=rules_capture,  # type: ignore[arg-type]
        scoring=ScoringService(),
        notifications=ConsoleNotificationService(),  # type: ignore[arg-type]
        extraction_version=settings.extraction_version,
    )

    message = VerificationJobMessage(
        documento_id=documento.id,
        cedula_registrada=args.cedula,
        placa_registrada=args.placa,
        nombre_registrado=args.nombre,
        tipo_declarado=args.tipo,
    )
    print("[smoke] VerificationPipeline.process_job …")
    pipeline.process_job(message)

    historial = repo.obtener_extraccion_idempotente(
        documento.id,
        ocr.prompt_hash,
        settings.extraction_version,
    )
    refreshed = repo.obtener_documento(documento.id)
    print("[smoke] ——— resumen ———")
    if historial is None:
        print("[smoke] no se encontró historial tras process_job")
        return 2

    rules_payload: dict[str, Any] | None = None
    if rules_capture.last is not None:
        ev = rules_capture.last
        rules_payload = {
            "has_reject": ev.has_reject,
            "has_manual": ev.has_manual,
            "details": [
                {
                    "rule_id": d.rule_id,
                    "passed": d.passed,
                    "severity": d.severity.value,
                    "message": d.message,
                }
                for d in ev.details
            ],
        }
        tipo = historial.tipo_detectado or ""
        rn02_fail = any(
            d.rule_id == "RN-02" and not d.passed for d in ev.details
        )
        if tipo in {"revisado", "permiso_pesos"} and rn02_fail:
            print(
                "[smoke] NOTA: RN-02 falló en tipo vehicular "
                f"({tipo}). Señalar para revisión futura de RN-02 "
                "universal vs docs centrados en placa (no corregir aún)."
            )

    print(
        json.dumps(
            {
                "documento_id": str(refreshed.id),
                "historial_id": str(historial.id),
                "resultado": (
                    historial.resultado.value
                    if hasattr(historial.resultado, "value")
                    else str(historial.resultado)
                ),
                "score_lectura": str(historial.score_lectura),
                "score_autenticidad": str(historial.score_autenticidad),
                "tipo_detectado": historial.tipo_detectado,
                "modelo_usado": historial.modelo_usado,
                "prompt_hash": historial.prompt_hash,
                "version_extraccion": historial.version_extraccion,
                "fecha_vencimiento": (
                    historial.fecha_vencimiento.isoformat()
                    if historial.fecha_vencimiento
                    else None
                ),
                "s3_key_verified": refreshed.s3_key_verified,
                "rules_evaluation": rules_payload,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print("[smoke] OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
