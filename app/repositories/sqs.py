"""Repositorio de mensajería SQS (cola de verificación)."""

from __future__ import annotations

import json

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.models.job import VerificationJobMessage
from app.repositories.exceptions import RepositoryError
from app.utils.logging import get_logger

logger = get_logger(__name__)


class SqsRepository:
    """Envío de jobs de verificación a la cola principal.

    Args:
        client: Cliente boto3 SQS inyectable.
        queue_url: URL de la cola. Si es ``None``, desde ApiSettings.
        region_name: Región AWS.
    """

    def __init__(
        self,
        *,
        client: object | None = None,
        queue_url: str | None = None,
        region_name: str | None = None,
    ) -> None:
        """Inicializa el repositorio SQS."""
        if queue_url is None or region_name is None:
            from app.config import get_api_settings

            api = get_api_settings()
            if queue_url is None:
                queue_url = api.aws_sqs_queue_url
            if region_name is None:
                region_name = api.aws_region

        self._queue_url = queue_url
        self._client = client or boto3.client("sqs", region_name=region_name)

    def enviar_mensaje_verificacion(self, message: VerificationJobMessage) -> str:
        """Publica un ``VerificationJobMessage`` en la cola worker.

        Args:
            message: Job tipado.

        Returns:
            ``MessageId`` de SQS (trazabilidad).

        Raises:
            RepositoryError: Si falla el envío.
        """
        body = message.model_dump(mode="json")
        try:
            response = self._client.send_message(
                QueueUrl=self._queue_url,
                MessageBody=json.dumps(body, default=str),
            )
        except (ClientError, BotoCoreError) as exc:
            logger.error(
                "sqs_send_failed",
                extra={"context": {"error": type(exc).__name__}},
            )
            raise RepositoryError("no se pudo encolar el job de verificación") from exc

        message_id = str(response.get("MessageId") or "")
        logger.info(
            "sqs_verification_enqueued",
            extra={
                "context": {
                    "documento_id": str(message.documento_id),
                    "sqs_message_id": message_id,
                }
            },
        )
        return message_id
