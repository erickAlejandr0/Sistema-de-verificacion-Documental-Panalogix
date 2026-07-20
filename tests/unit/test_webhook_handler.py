"""Unit: webhook_handler siempre ack (nunca propaga a SNS)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.handlers import webhook_handler as wh


def test_handler_malformed_records_returns_dict_without_raise() -> None:
    """Records ausente / no-lista / basura → dict ack, sin excepción."""
    with patch.object(wh, "WebhookService") as svc_cls:
        svc = MagicMock()
        svc.deliver_from_sns_record.return_value = True
        svc_cls.return_value = svc

        for event in ({}, {"Records": None}, {"Records": "no-list"}, {"Records": [1, "x"]}):
            result = wh.handler(event, object())
            assert isinstance(result, dict)
            assert "delivered" in result
            assert "failed" in result
            assert result.get("ok") is True


def test_handler_settings_failure_returns_dict_without_raise() -> None:
    """Fallo al construir WebhookService → dict fatal, sin raise."""
    with patch.object(wh, "WebhookService", side_effect=RuntimeError("settings boom")):
        result = wh.handler({"Records": []}, object())
    assert result["ok"] is False
    assert result["error"] == "RuntimeError"
    assert result["delivered"] == 0


def test_handler_deliver_false_still_acks() -> None:
    """Agotar retries HTTP (False) no propaga; cuenta como failed."""
    with patch.object(wh, "WebhookService") as svc_cls:
        svc = MagicMock()
        svc.deliver_from_sns_record.return_value = False
        svc_cls.return_value = svc
        result = wh.handler(
            {"Records": [{"Sns": {"Message": "{}"}}]},
            object(),
        )
    assert result["ok"] is True
    assert result["failed"] == 1
    assert result["delivered"] == 0
