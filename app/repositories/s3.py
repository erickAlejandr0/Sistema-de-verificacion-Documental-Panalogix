"""Repositorio de objetos en S3 (raw-docs / verified-docs)."""

from __future__ import annotations

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.repositories.exceptions import S3ObjectNotFoundError, S3RepositoryError
from app.utils.logging import get_logger

logger = get_logger(__name__)


class S3Repository:
    """Operaciones sobre buckets de documentos del SVD.

    Args:
        client: Cliente boto3 S3 inyectable.
        raw_bucket: Nombre del bucket raw. Si es ``None``, desde settings.
        verified_bucket: Nombre del bucket verified. Si es ``None``, settings.
        region_name: Región AWS.
    """

    def __init__(
        self,
        *,
        client: object | None = None,
        raw_bucket: str | None = None,
        verified_bucket: str | None = None,
        region_name: str | None = None,
    ) -> None:
        """Inicializa el repositorio S3."""
        if raw_bucket is None or verified_bucket is None or region_name is None:
            from app.config import get_worker_settings

            ws = get_worker_settings()
            if raw_bucket is None:
                raw_bucket = ws.aws_s3_raw_bucket
            if verified_bucket is None:
                verified_bucket = ws.aws_s3_verified_bucket
            if region_name is None:
                region_name = ws.aws_region

        self._raw_bucket = raw_bucket
        self._verified_bucket = verified_bucket
        self._client = client or boto3.client("s3", region_name=region_name)

    def descargar_raw(self, key: str) -> bytes:
        """Descarga un objeto del bucket raw-docs.

        Args:
            key: Clave S3.

        Returns:
            Contenido binario del objeto.

        Raises:
            S3ObjectNotFoundError: Si el objeto no existe.
            S3RepositoryError: Otros errores de S3.
        """
        return self._get_object(self._raw_bucket, key)

    def subir_verified(
        self,
        key: str,
        body: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Sube un objeto al bucket verified-docs.

        Args:
            key: Clave destino.
            body: Contenido.
            content_type: MIME type.

        Returns:
            La misma ``key`` persistida.

        Raises:
            S3RepositoryError: Si falla el put.
        """
        try:
            self._client.put_object(
                Bucket=self._verified_bucket,
                Key=key,
                Body=body,
                ContentType=content_type,
            )
            return key
        except (ClientError, BotoCoreError) as exc:
            logger.error(
                "s3_put_verified_failed",
                extra={"context": {"error": type(exc).__name__}},
            )
            raise S3RepositoryError("no se pudo subir el objeto verified") from exc

    def generar_presigned_post_raw(
        self,
        *,
        key: str,
        content_type: str,
        max_bytes: int = 10 * 1024 * 1024,
        expires_in: int = 900,
    ) -> dict[str, object]:
        """Genera un POST firmado al bucket raw con límites de tipo y tamaño.

        Args:
            key: Clave S3 destino.
            content_type: MIME permitido (jpeg/png/pdf).
            max_bytes: Tamaño máximo del objeto (default 10 MiB).
            expires_in: Segundos de validez de la URL.

        Returns:
            Dict con ``url``, ``fields`` (form fields de boto3) y ``s3_key``.

        Raises:
            S3RepositoryError: Si falla la firma.
        """
        try:
            post = self._client.generate_presigned_post(
                Bucket=self._raw_bucket,
                Key=key,
                Fields={"Content-Type": content_type},
                Conditions=[
                    {"Content-Type": content_type},
                    ["content-length-range", 1, max_bytes],
                ],
                ExpiresIn=expires_in,
            )
        except (ClientError, BotoCoreError) as exc:
            logger.error(
                "s3_presign_post_failed",
                extra={"context": {"error": type(exc).__name__}},
            )
            raise S3RepositoryError("no se pudo generar URL firmada") from exc

        return {
            "url": post["url"],
            "fields": post["fields"],
            "s3_key": key,
        }

    def eliminar(self, key: str, *, verified: bool = False) -> None:
        """Elimina un objeto del bucket raw o verified.

        Args:
            key: Clave S3.
            verified: Si True, usa verified-docs; si False, raw-docs.

        Raises:
            S3RepositoryError: Si falla el delete.
        """
        bucket = self._verified_bucket if verified else self._raw_bucket
        try:
            self._client.delete_object(Bucket=bucket, Key=key)
        except (ClientError, BotoCoreError) as exc:
            logger.error(
                "s3_delete_failed",
                extra={"context": {"error": type(exc).__name__, "verified": verified}},
            )
            raise S3RepositoryError("no se pudo eliminar el objeto S3") from exc

    def _get_object(self, bucket: str, key: str) -> bytes:
        """GET de un objeto S3."""
        try:
            response = self._client.get_object(Bucket=bucket, Key=key)
            body = response["Body"].read()
            return bytes(body)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in {"404", "NoSuchKey", "NotFound"}:
                raise S3ObjectNotFoundError(f"objeto s3://{bucket}/{key} no existe") from exc
            logger.error(
                "s3_get_failed",
                extra={"context": {"error": type(exc).__name__}},
            )
            raise S3RepositoryError("no se pudo descargar el objeto S3") from exc
        except BotoCoreError as exc:
            raise S3RepositoryError("no se pudo descargar el objeto S3") from exc
