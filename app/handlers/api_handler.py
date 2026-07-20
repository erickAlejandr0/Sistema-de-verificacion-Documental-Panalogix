"""Handler Lambda de la API REST del SVD (M-API / P6.1).

Ruteo por condicionales sobre ``httpMethod`` + ``path`` (sin FastAPI/Flask/
Mangum). Orquesta autenticación servicio-a-servicio, repos y
``NotificationService``.

Auth:
    Header ``X-SVD-Api-Key`` comparado contra ``PANALOGIX_API_KEY`` o
    ``RETOOL_API_KEY`` (env; SSM resolve en el template futuro). Log
    estructurado con ``api_client``: ``panalogix`` | ``retool``.

    Matriz authZ:
        - panalogix: POST /verificaciones, GET /verificaciones/{tid},
          POST /verificaciones/generar-url
        - retool: GET /verificaciones/pendientes,
          POST /verificaciones/{id}/resolver

Infra SAM (API Gateway + Lambda + IAM) es tarea separada; este módulo solo
implementa el código del handler.
"""

from __future__ import annotations

import base64
import hmac
import json
import re
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import ValidationError

from app.models.correccion import CorreccionCreate
from app.models.documento import DocumentoCreate
from app.models.enums import ResultadoVerificacion
from app.models.job import (
    CrearVerificacionRequest,
    GenerarUrlRequest,
    PendientesQuery,
    ResolverVerificacionRequest,
    VerificationJobMessage,
)
from app.repositories.exceptions import (
    DocumentNotFoundError,
    HistorialNotFoundError,
    RepositoryError,
    S3RepositoryError,
)
from app.repositories.s3 import S3Repository
from app.repositories.sqs import SqsRepository
from app.repositories.verificacion import VerificacionRepository
from app.services.notificacion_mapper import (
    resultado_to_str,
    to_resultado_publicacion,
)
from app.services.sns import (
    NonRetryableNotificationError,
    NotificationService,
    RetryableNotificationError,
)
from app.utils.logging import get_logger
from app.utils.metrics import (
    emit_count,
    normalize_campo_corregido_dimension,
)

logger = get_logger(__name__)

ApiClient = Literal["panalogix", "retool"]

_API_KEY_HEADER = "x-svd-api-key"
_MAX_UPLOAD_BYTES = 10 * 1024 * 1024

_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

# (method, path_pattern) — path_pattern usa {uuid} para segmentos UUID.
_PANALOGIX_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("POST", "/verificaciones"),
        ("GET", "/verificaciones/{uuid}"),
        ("POST", "/verificaciones/generar-url"),
    }
)
_RETOOL_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", "/verificaciones/pendientes"),
        ("POST", "/verificaciones/{uuid}/resolver"),
    }
)


def _json_response(status: int, body: dict[str, Any] | list[Any]) -> dict[str, Any]:
    """Respuesta API Gateway REST (proxy integration)."""
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Cache-Control": "no-store",
        },
        "body": json.dumps(body, default=str),
    }


def _error(status: int, message: str) -> dict[str, Any]:
    """Cuerpo de error tipado (sin stack traces)."""
    return _json_response(status, {"error": message})


def _normalize_path(raw_path: str) -> str:
    """Normaliza path (sin stage, sin slash final salvo root)."""
    path = raw_path.split("?", 1)[0]
    # API Gateway stage prefix: /prod/verificaciones → /verificaciones
    parts = [p for p in path.split("/") if p]
    if parts and parts[0] in {"prod", "staging", "dev", "Stage"}:
        parts = parts[1:]
    normalized = "/" + "/".join(parts) if parts else "/"
    if normalized != "/" and normalized.endswith("/"):
        normalized = normalized.rstrip("/")
    return normalized


def _header_api_key(event: dict[str, Any]) -> str | None:
    """Extrae X-SVD-Api-Key (case-insensitive)."""
    headers = event.get("headers") or {}
    if not isinstance(headers, dict):
        return None
    for key, value in headers.items():
        if str(key).lower() == _API_KEY_HEADER and value:
            return str(value).strip()
    return None


def _keys_match(provided: str, expected: str) -> bool:
    """Comparación en tiempo constante; False si longitudes difieren."""
    if len(provided) != len(expected):
        return False
    return hmac.compare_digest(provided, expected)


def _authenticate(event: dict[str, Any]) -> ApiClient | None:
    """Valida la API key y retorna el cliente, o None si falla."""
    from app.config import get_api_settings

    provided = _header_api_key(event)
    if not provided:
        return None

    settings = get_api_settings()
    if _keys_match(provided, settings.panalogix_api_key):
        return "panalogix"
    if _keys_match(provided, settings.retool_api_key):
        return "retool"
    return None


def _match_route(method: str, path: str) -> tuple[str, str] | None:
    """Devuelve (method, pattern) canónico o None si no hay match."""
    if method == "POST" and path == "/verificaciones":
        return ("POST", "/verificaciones")
    if method == "POST" and path == "/verificaciones/generar-url":
        return ("POST", "/verificaciones/generar-url")
    if method == "GET" and path == "/verificaciones/pendientes":
        return ("GET", "/verificaciones/pendientes")

    m = re.fullmatch(r"/verificaciones/([^/]+)/resolver", path)
    if method == "POST" and m and _UUID_RE.fullmatch(m.group(1)):
        return ("POST", "/verificaciones/{uuid}/resolver")

    m = re.fullmatch(r"/verificaciones/([^/]+)", path)
    if method == "GET" and m and _UUID_RE.fullmatch(m.group(1)):
        return ("GET", "/verificaciones/{uuid}")

    return None


def _authorize(api_client: ApiClient, method: str, path: str) -> bool:
    """True si el cliente puede invocar la ruta."""
    route = _match_route(method, path)
    if route is None:
        return False
    if api_client == "panalogix":
        return route in _PANALOGIX_ROUTES
    return route in _RETOOL_ROUTES


def _parse_json_body(event: dict[str, Any]) -> dict[str, Any]:
    """Parsea body JSON (soporta base64 de API Gateway)."""
    raw = event.get("body")
    if raw is None or raw == "":
        return {}
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode("utf-8")
    if not isinstance(raw, str):
        raise ValueError("body inválido")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("body debe ser un objeto JSON")
    return data


def _path_uuid(path: str, *, position: int = -1) -> UUID:
    """Extrae UUID de un segmento del path."""
    parts = [p for p in path.split("/") if p]
    token = parts[position]
    return UUID(token)


class ApiPipeline:
    """Orquestador inyectable de la API REST."""

    def __init__(
        self,
        *,
        verificacion_repo: VerificacionRepository | None = None,
        s3_repo: S3Repository | None = None,
        sqs_repo: SqsRepository | None = None,
        notifications: NotificationService | None = None,
    ) -> None:
        """Inicializa dependencias (defaults desde settings / constructores)."""
        self._repo = verificacion_repo or VerificacionRepository()
        if s3_repo is None or sqs_repo is None or notifications is None:
            from app.config import get_api_settings

            settings = get_api_settings()
            if s3_repo is None:
                s3_repo = S3Repository(
                    raw_bucket=settings.aws_s3_raw_bucket,
                    verified_bucket=settings.aws_s3_raw_bucket,
                    region_name=settings.aws_region,
                )
            if sqs_repo is None:
                sqs_repo = SqsRepository(
                    queue_url=settings.aws_sqs_queue_url,
                    region_name=settings.aws_region,
                )
            if notifications is None:
                notifications = NotificationService(
                    topic_arn=settings.aws_sns_topic_arn,
                    region_name=settings.aws_region,
                )
        self._s3 = s3_repo
        self._sqs = sqs_repo
        self._notifications = notifications

    def crear_verificacion(self, body: dict[str, Any]) -> dict[str, Any]:
        """POST /verificaciones → 202."""
        req = CrearVerificacionRequest.model_validate(body)
        tipo_doc = req.tipo_documento
        tipo_decl = req.tipo_declarado or tipo_doc
        documento = self._repo.crear_documento(
            DocumentoCreate(
                transportista_id=req.transportista_id,
                tipo_documento=tipo_doc,
                s3_key_raw=req.s3_key_raw,
            )
        )
        job = VerificationJobMessage(
            documento_id=documento.id,
            cedula_registrada=req.cedula_registrada,
            placa_registrada=req.placa_registrada,
            nombre_registrado=req.nombre_registrado,
            tipo_declarado=tipo_decl,
        )
        self._sqs.enviar_mensaje_verificacion(job)
        return _json_response(202, {"documento_id": str(documento.id)})

    def listar_por_transportista(self, transportista_id: UUID) -> dict[str, Any]:
        """GET /verificaciones/{transportista_id} → 200."""
        items = self._repo.listar_con_ultimo_historial(transportista_id)
        payload = [item.model_dump(mode="json") for item in items]
        return _json_response(200, {"items": payload})

    def listar_pendientes(self, query: dict[str, str | None]) -> dict[str, Any]:
        """GET /verificaciones/pendientes → 200."""
        params = PendientesQuery.model_validate(
            {
                "limit": query.get("limit") or 50,
                "offset": query.get("offset") or 0,
            }
        )
        items = self._repo.listar_pendientes_revision(
            limit=params.limit,
            offset=params.offset,
        )
        return _json_response(
            200,
            {
                "items": [h.model_dump(mode="json") for h in items],
                "limit": params.limit,
                "offset": params.offset,
            },
        )

    def resolver(self, historial_id: UUID, body: dict[str, Any]) -> dict[str, Any]:
        """POST /verificaciones/{id}/resolver → 200.

        ``corregido_por`` es el identificador de usuario de Retool (texto
        simple, p. ej. email), inyectado desde la sesión autenticada de
        Retool y configurado como campo no editable en el formulario — no
        un UUID relacional, no texto libre digitado por el revisor. El SVD
        confía en el valor del body sin validarlo contra ninguna identidad
        propia (sin login/JWT en el SVD): decisión de costo-beneficio del
        MVP.

        ``correcciones`` puede ser una lista vacía: solo se actualiza el
        resultado; ``corregido_por`` top-level se reutiliza al registrar
        cada ítem de corrección cuando la lista no está vacía.
        """
        req = ResolverVerificacionRequest.model_validate(body)
        # Una sola carga: existencia + dims de métricas (sin SELECT extra).
        historial_prev, _pii = self._repo.obtener_extraccion(
            historial_id, decrypt_pii=False
        )
        tipo_doc = (historial_prev.tipo_detectado or "desconocido").strip() or (
            "desconocido"
        )
        resultado_anterior = resultado_to_str(historial_prev.resultado)

        for item in req.correcciones:
            self._repo.registrar_correccion(
                CorreccionCreate(
                    historial_id=historial_id,
                    campo_corregido=item.campo_corregido,
                    valor_modelo=item.valor_modelo,
                    valor_correcto=item.valor_correcto,
                    corregido_por=req.corregido_por,
                )
            )
            emit_count(
                "CorreccionesRegistradas",
                dimensions={
                    "tipo_documento": tipo_doc,
                    "campo_corregido": normalize_campo_corregido_dimension(
                        item.campo_corregido
                    ),
                },
            )

        historial = self._repo.actualizar_resultado_historial(
            historial_id,
            ResultadoVerificacion(req.resultado),
        )
        emit_count(
            "ResolucionesManuales",
            dimensions={
                "tipo_documento": tipo_doc,
                "resultado_anterior": resultado_anterior,
                "resultado_nuevo": req.resultado,
            },
        )
        documento = self._repo.obtener_documento(historial.documento_id)
        payload = to_resultado_publicacion(documento, historial)
        self._notifications.publicar_resultado(payload)
        self._repo.marcar_alertas_pendientes_atendidas(historial_id)
        return _json_response(200, historial.model_dump(mode="json"))

    def generar_url(self, body: dict[str, Any]) -> dict[str, Any]:
        """POST /verificaciones/generar-url → 200 (presigned POST S3)."""
        req = GenerarUrlRequest.model_validate(body)
        ext = {
            "image/jpeg": "jpg",
            "image/png": "png",
            "application/pdf": "pdf",
        }[req.content_type]
        key = f"uploads/{uuid4()}.{ext}"
        result = self._s3.generar_presigned_post_raw(
            key=key,
            content_type=req.content_type,
            max_bytes=_MAX_UPLOAD_BYTES,
        )
        return _json_response(200, result)


def handler(event: dict[str, Any], context: object) -> dict[str, Any]:
    """Punto de entrada Lambda (API Gateway REST).

    Args:
        event: Evento API Gateway (v1).
        context: Contexto Lambda (ignorado).

    Returns:
        Respuesta proxy con statusCode/headers/body JSON.
    """
    del context
    method = str(event.get("httpMethod") or "").upper()
    path = _normalize_path(str(event.get("path") or event.get("resource") or "/"))

    api_client = _authenticate(event)
    if api_client is None:
        logger.warning(
            "api_auth_failed",
            extra={"context": {"method": method, "path": path}},
        )
        return _error(401, "unauthorized")

    logger.info(
        "api_request",
        extra={
            "context": {
                "api_client": api_client,
                "method": method,
                "path": path,
            }
        },
    )

    if _match_route(method, path) is None:
        return _error(404, "not found")

    if not _authorize(api_client, method, path):
        logger.warning(
            "api_forbidden",
            extra={
                "context": {
                    "api_client": api_client,
                    "method": method,
                    "path": path,
                }
            },
        )
        return _error(403, "forbidden")

    pipeline = ApiPipeline()
    try:
        if method == "POST" and path == "/verificaciones":
            return pipeline.crear_verificacion(_parse_json_body(event))
        if method == "POST" and path == "/verificaciones/generar-url":
            return pipeline.generar_url(_parse_json_body(event))
        if method == "GET" and path == "/verificaciones/pendientes":
            qs = event.get("queryStringParameters") or {}
            if not isinstance(qs, dict):
                qs = {}
            return pipeline.listar_pendientes(qs)
        if method == "POST" and path.endswith("/resolver"):
            return pipeline.resolver(_path_uuid(path, position=-2), _parse_json_body(event))
        if method == "GET" and path.startswith("/verificaciones/"):
            return pipeline.listar_por_transportista(_path_uuid(path, position=-1))
        return _error(404, "not found")
    except ValidationError as exc:
        logger.info(
            "api_validation_error",
            extra={
                "context": {
                    "api_client": api_client,
                    "errors": exc.errors(include_url=False),
                }
            },
        )
        return _error(422, "validation error")
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError) as exc:
        logger.info(
            "api_bad_request",
            extra={
                "context": {
                    "api_client": api_client,
                    "error": type(exc).__name__,
                }
            },
        )
        return _error(400, "bad request")
    except (DocumentNotFoundError, HistorialNotFoundError) as exc:
        logger.info(
            "api_not_found",
            extra={
                "context": {
                    "api_client": api_client,
                    "error": type(exc).__name__,
                }
            },
        )
        return _error(404, "not found")
    except (
        RepositoryError,
        S3RepositoryError,
        NonRetryableNotificationError,
        RetryableNotificationError,
    ) as exc:
        logger.error(
            "api_upstream_error",
            extra={
                "context": {
                    "api_client": api_client,
                    "error": type(exc).__name__,
                }
            },
        )
        return _error(500, "internal error")
