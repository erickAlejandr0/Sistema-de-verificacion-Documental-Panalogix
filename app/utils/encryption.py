"""Cifrado y descifrado de PII con AWS KMS.

Cumplimiento Ley 81 de 2019: los datos personales sensibles deben cifrarse
antes de persistirse en ``historial.campos_cifrados``.
"""

from __future__ import annotations

import base64

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.utils.logging import get_logger

logger = get_logger(__name__)


class EncryptionError(Exception):
    """Error base del módulo de cifrado PII."""


class KmsEncryptionError(EncryptionError):
    """Fallo al invocar AWS KMS."""


class PiiEncryptor:
    """Cifrador de campos PII mediante AWS KMS.

    Args:
        kms_key_id: Identificador de la clave KMS. Si es ``None``, se lee
            desde ``settings.kms_key_id``.
        region_name: Región AWS. Si es ``None``, se lee de settings.
        client: Cliente boto3 KMS inyectable (tests).
    """

    def __init__(
        self,
        kms_key_id: str | None = None,
        *,
        region_name: str | None = None,
        client: object | None = None,
    ) -> None:
        """Inicializa el cifrador con la clave KMS configurada.

        Args:
            kms_key_id: ID o ARN de la clave KMS.
            region_name: Región AWS del cliente KMS.
            client: Cliente boto3 opcional.

        Raises:
            EncryptionError: Si el ``kms_key_id`` resultante está vacío.
        """
        if kms_key_id is None or region_name is None:
            from app.config import get_common_settings

            common = get_common_settings()
            if kms_key_id is None:
                kms_key_id = common.kms_key_id
            if region_name is None:
                region_name = common.aws_region

        if not kms_key_id or not kms_key_id.strip():
            raise EncryptionError("kms_key_id es obligatorio para cifrar PII")

        self._kms_key_id: str = kms_key_id.strip()
        self._client = client or boto3.client("kms", region_name=region_name)

    @property
    def kms_key_id(self) -> str:
        """Identificador de la clave KMS usada por este cifrador."""
        return self._kms_key_id

    def encrypt(self, plaintext: str) -> str:
        """Cifra un valor PII en claro con KMS.

        Args:
            plaintext: Texto en claro (p. ej. cédula o nombre).

        Returns:
            Ciphertext en base64 listo para ``historial.campos_cifrados``.

        Raises:
            EncryptionError: Si el plaintext está vacío.
            KmsEncryptionError: Si la llamada a KMS falla.
        """
        if not plaintext or not plaintext.strip():
            raise EncryptionError("el plaintext PII no puede estar vacío")

        try:
            response = self._client.encrypt(
                KeyId=self._kms_key_id,
                Plaintext=plaintext.encode("utf-8"),
            )
            ciphertext: bytes = response["CiphertextBlob"]
            return base64.b64encode(ciphertext).decode("ascii")
        except (ClientError, BotoCoreError) as exc:
            logger.error(
                "kms_encrypt_failed",
                extra={"context": {"error": type(exc).__name__}},
            )
            raise KmsEncryptionError("fallo al cifrar PII con KMS") from exc

    def decrypt(self, ciphertext: str) -> str:
        """Descifra un valor PII previamente cifrado con KMS.

        Args:
            ciphertext: Valor cifrado (base64) en ``campos_cifrados``.

        Returns:
            Texto en claro recuperado.

        Raises:
            EncryptionError: Si el ciphertext está vacío o mal formado.
            KmsEncryptionError: Si la llamada a KMS falla.
        """
        if not ciphertext or not ciphertext.strip():
            raise EncryptionError("el ciphertext PII no puede estar vacío")

        try:
            raw = base64.b64decode(ciphertext.encode("ascii"), validate=True)
            response = self._client.decrypt(CiphertextBlob=raw)
            plaintext_bytes: bytes = response["Plaintext"]
            return plaintext_bytes.decode("utf-8")
        except (ClientError, BotoCoreError, ValueError) as exc:
            logger.error(
                "kms_decrypt_failed",
                extra={"context": {"error": type(exc).__name__}},
            )
            raise KmsEncryptionError("fallo al descifrar PII con KMS") from exc


# Alias de compatibilidad con el nombre anterior del stub.
KmsIntegrationPendingError = KmsEncryptionError
