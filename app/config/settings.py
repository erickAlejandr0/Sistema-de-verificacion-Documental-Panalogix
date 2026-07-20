"""Settings del SVD leídos desde variables de entorno.

``CommonSettings`` cubre Worker, Alertas y API (SNS, RDS, KMS, región).
``WorkerSettings`` añade Anthropic / S3 verified / umbrales OCR.
``ApiSettings`` añade API keys (Panalogix/Retool), bucket raw y cola SQS.
``WebhookSettings`` es aislado (no CommonSettings): solo URL + secreto HMAC.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_SETTINGS_CONFIG = SettingsConfigDict(
    env_file=".env",
    env_file_encoding="utf-8",
    extra="ignore",
)


class CommonSettings(BaseSettings):
    """Configuración compartida (Worker y Alerts).

    Attributes:
        aws_region: Región AWS.
        aws_sns_topic_arn: ARN del topic SNS.
        database_url: URL de RDS PostgreSQL.
        kms_key_id: Alias/ARN de la CMK PII existente (``alias/panalogix-pii``).
        environment: Ambiente de ejecución.
    """

    model_config = _SETTINGS_CONFIG

    aws_region: str = Field(
        ...,
        min_length=1,
        validation_alias="AWS_REGION",
        description="Región AWS.",
    )
    aws_sns_topic_arn: str = Field(
        ...,
        min_length=1,
        validation_alias="AWS_SNS_TOPIC_ARN",
        description="ARN del topic SNS de resultados.",
    )
    database_url: str = Field(
        ...,
        min_length=1,
        validation_alias="DATABASE_URL",
        description="URL de conexión a RDS PostgreSQL.",
    )
    kms_key_id: str = Field(
        ...,
        min_length=1,
        validation_alias="KMS_KEY_ID",
        description="Alias o ARN de la clave KMS PII (existente).",
    )
    environment: Literal["dev", "staging", "prod"] = Field(
        ...,
        validation_alias="ENVIRONMENT",
        description="Ambiente de ejecución.",
    )


class WorkerSettings(CommonSettings):
    """Configuración del worker de verificación (incluye OCR / S3 / SQS)."""

    anthropic_api_key: str = Field(
        ...,
        min_length=1,
        validation_alias="ANTHROPIC_API_KEY",
        description="Clave de API de Anthropic.",
    )
    aws_s3_raw_bucket: str = Field(
        ...,
        min_length=1,
        validation_alias="AWS_S3_RAW_BUCKET",
        description="Bucket S3 de documentos raw.",
    )
    aws_s3_verified_bucket: str = Field(
        ...,
        min_length=1,
        validation_alias="AWS_S3_VERIFIED_BUCKET",
        description="Bucket S3 de documentos verificados.",
    )
    aws_sqs_queue_url: str = Field(
        ...,
        min_length=1,
        validation_alias="AWS_SQS_QUEUE_URL",
        description="URL de la cola SQS principal.",
    )
    primary_model: str = Field(
        ...,
        min_length=1,
        validation_alias="MODELO_PRIMARIO",
        description="Modelo Claude primario (estratégia híbrida).",
    )
    fallback_model: str = Field(
        ...,
        min_length=1,
        validation_alias="MODELO_FALLBACK",
        description="Modelo Claude de respaldo cuando baja la confianza.",
    )
    confidence_threshold: float = Field(
        ...,
        validation_alias="UMBRAL_CONFIANZA",
        description="Umbral de confianza de extracción (0.0–1.0).",
    )
    authenticity_threshold: float = Field(
        ...,
        validation_alias="UMBRAL_AUTENTICIDAD",
        description="Umbral de autenticidad para revisión manual (0.0–1.0).",
    )
    max_pdf_pages: int = Field(
        default=5,
        ge=1,
        validation_alias="MAX_PAGINAS_PDF",
        description="Máximo de páginas PDF a convertir (RF-06 / pdf2image).",
    )
    auth_penalty_anomalia: float = Field(
        default=0.100,
        validation_alias="AUTH_PENALTY_ANOMALIA",
        description="Penalización de autenticidad por cada anomalía.",
    )
    auth_penalty_temporal: float = Field(
        default=0.200,
        validation_alias="AUTH_PENALTY_TEMPORAL",
        description="Penalización si validacion_temporal_ok es False.",
    )
    auth_penalty_exif: float = Field(
        default=0.150,
        validation_alias="AUTH_PENALTY_EXIF",
        description="Penalización si EXIF es sospechoso.",
    )
    extraction_version: str = Field(
        default="1.0.0",
        min_length=1,
        max_length=20,
        validation_alias="VERSION_EXTRACCION",
        description="Versión del pipeline de extracción.",
    )

    @field_validator(
        "confidence_threshold",
        "authenticity_threshold",
        "auth_penalty_anomalia",
        "auth_penalty_temporal",
        "auth_penalty_exif",
    )
    @classmethod
    def validate_threshold_range(cls, value: float) -> float:
        """Valida que el valor esté en el intervalo [0.0, 1.0]."""
        if not 0.0 <= value <= 1.0:
            raise ValueError("el valor debe estar entre 0.0 y 1.0 inclusive")
        return value


class ApiSettings(CommonSettings):
    """Configuración de la Lambda API REST.

    Incluye keys de servicio y recursos de ingesta (raw S3 + SQS).
    Sin Anthropic ni umbrales OCR.
    """

    panalogix_api_key: str = Field(
        ...,
        min_length=1,
        validation_alias="PANALOGIX_API_KEY",
        description="API key servicio Panalogix (header X-SVD-Api-Key).",
    )
    retool_api_key: str = Field(
        ...,
        min_length=1,
        validation_alias="RETOOL_API_KEY",
        description="API key servicio Retool (header X-SVD-Api-Key).",
    )
    aws_s3_raw_bucket: str = Field(
        ...,
        min_length=1,
        validation_alias="AWS_S3_RAW_BUCKET",
        description="Bucket S3 de documentos raw (presigned upload).",
    )
    aws_sqs_queue_url: str = Field(
        ...,
        min_length=1,
        validation_alias="AWS_SQS_QUEUE_URL",
        description="URL de la cola SQS de verificación.",
    )


@lru_cache(maxsize=1)
def get_common_settings() -> CommonSettings:
    """Singleton lazy de ajustes compartidos."""
    return CommonSettings()


@lru_cache(maxsize=1)
def get_worker_settings() -> WorkerSettings:
    """Singleton lazy de ajustes del worker."""
    return WorkerSettings()


@lru_cache(maxsize=1)
def get_api_settings() -> ApiSettings:
    """Singleton lazy de ajustes de la API REST."""
    return ApiSettings()


class WebhookSettings(BaseSettings):
    """Config exclusiva del emisor webhook (M-WEBHOOK).

    No hereda ``CommonSettings`` a propósito: esta Lambda no usa RDS, SNS
    publish, KMS PII ni API keys. Superficie mínima de secretos — solo
    destino HTTPS y secreto HMAC (ni ``aws_region``). Aislamiento más
    estricto que Alerts/API, intencional y no un descuido de patrón.

    Attributes:
        webhook_url: URL HTTPS del receptor (sin default de dominio).
        webhook_hmac_secret: Secreto compartido para firma HMAC-SHA256.
        webhook_timeout_seconds: Timeout HTTP por intento.
        webhook_max_attempts: Intentos totales (1 + retries).
            Infra SAM futura: el Timeout de la Lambda debe cubrir el peor
            caso de reintentos — backoff 1+2+4=7s más hasta 3 timeouts HTTP
            de 10s ≈ 37s; usar margen (p. ej. 60s) para no truncar a mitad
            de un reintento.
    """

    model_config = _SETTINGS_CONFIG

    webhook_url: str = Field(
        ...,
        min_length=8,
        validation_alias="WEBHOOK_URL",
        description="URL HTTPS del webhook receptor (configurable; sin default).",
    )
    webhook_hmac_secret: str = Field(
        ...,
        min_length=1,
        validation_alias="WEBHOOK_HMAC_SECRET",
        description="Secreto HMAC compartido con el receptor.",
    )
    webhook_timeout_seconds: float = Field(
        default=10.0,
        gt=0,
        validation_alias="WEBHOOK_TIMEOUT_SECONDS",
        description="Timeout HTTP por intento (segundos).",
    )
    # Peor caso ~37s (7s backoff + 3×10s HTTP). Timeout Lambda SAM futuro: ≥60s.
    webhook_max_attempts: int = Field(
        default=3,
        ge=1,
        le=10,
        validation_alias="WEBHOOK_MAX_ATTEMPTS",
        description="Intentos de entrega (incluye el primero).",
    )

    @field_validator("webhook_url")
    @classmethod
    def validate_https_url(cls, value: str) -> str:
        """Exige HTTPS; no asume ningún dominio concreto."""
        cleaned = value.strip()
        if not cleaned.lower().startswith("https://"):
            raise ValueError("WEBHOOK_URL debe usar HTTPS")
        return cleaned


@lru_cache(maxsize=1)
def get_webhook_settings() -> WebhookSettings:
    """Singleton lazy de ajustes del emisor webhook."""
    return WebhookSettings()
