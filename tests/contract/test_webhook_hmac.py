"""Contrato: firma HMAC y body crudo del webhook (P6.2 / docs)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.services.webhook_service import WebhookService, sign_body
from tests.conftest import (
    WEBHOOK_CONTRACT_BODY,
    WEBHOOK_CONTRACT_SECRET,
    WEBHOOK_CONTRACT_SIGNATURE,
)


@pytest.mark.contract
def test_sign_body_matches_documented_hmac_vector() -> None:
    """Vector de docs/contrato-webhook-panalogix.md debe coincidir exactamente."""
    assert (
        sign_body(WEBHOOK_CONTRACT_SECRET, WEBHOOK_CONTRACT_BODY)
        == WEBHOOK_CONTRACT_SIGNATURE
    )


@pytest.mark.contract
def test_deliver_posts_raw_bytes_without_reserializing() -> None:
    """El POST usa la misma identidad de bytes del Message (sin json dumps)."""
    captured: dict[str, object] = {}

    class _Resp:
        status = 200

        def read(self) -> bytes:
            return b"ok"

        def getcode(self) -> int:
            return 200

        def __enter__(self) -> _Resp:
            return self

        def __exit__(self, *args: object) -> bool:
            return False

    def fake_urlopen(req: object, timeout: float | None = None) -> _Resp:
        captured["data"] = getattr(req, "data", None)
        headers = getattr(req, "headers", {}) or {}
        # urllib may Title-Case header keys
        sig = None
        for key, value in headers.items():
            if str(key).lower() == "x-svd-signature":
                sig = value
                break
        captured["signature"] = sig
        return _Resp()

    service = WebhookService(
        url="https://receptor.example.com/hooks/svd",
        secret=WEBHOOK_CONTRACT_SECRET,
        timeout_seconds=5.0,
        max_attempts=1,
        urlopen=fake_urlopen,
    )
    assert service.deliver(
        body=WEBHOOK_CONTRACT_BODY,
        event_type="verificacion_resultado",
    )

    assert captured["data"] is WEBHOOK_CONTRACT_BODY
    assert captured["signature"] == WEBHOOK_CONTRACT_SIGNATURE


@pytest.mark.contract
def test_deliver_from_sns_record_preserves_message_bytes() -> None:
    """SNS Message string → UTF-8 bytes exactos firmados/enviados."""
    captured: dict[str, object] = {}

    class _Resp:
        status = 200

        def read(self) -> bytes:
            return b""

        def getcode(self) -> int:
            return 200

        def __enter__(self) -> _Resp:
            return self

        def __exit__(self, *args: object) -> bool:
            return False

    def fake_urlopen(req: object, timeout: float | None = None) -> _Resp:
        captured["data"] = getattr(req, "data", None)
        return _Resp()

    raw_str = WEBHOOK_CONTRACT_BODY.decode("utf-8")
    service = WebhookService(
        url="https://receptor.example.com/hooks/svd",
        secret=WEBHOOK_CONTRACT_SECRET,
        timeout_seconds=5.0,
        max_attempts=1,
        urlopen=fake_urlopen,
    )
    ok = service.deliver_from_sns_record(
        {
            "Sns": {
                "Message": raw_str,
                "MessageAttributes": {
                    "event_type": {
                        "Type": "String",
                        "Value": "verificacion_resultado",
                    }
                },
            }
        }
    )
    assert ok is True
    assert captured["data"] == WEBHOOK_CONTRACT_BODY
