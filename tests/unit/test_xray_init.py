"""Tests unitarios del bootstrap X-Ray — sin daemon ni credenciales AWS."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from app.utils import tracing as tracing_mod


@pytest.fixture(autouse=True)
def _reset_tracing_flags() -> None:
    tracing_mod._reset_for_tests()
    yield
    tracing_mod._reset_for_tests()


def test_configure_xray_calls_patch_all_once() -> None:
    mock_patch_all = MagicMock()
    mock_patch = MagicMock()
    with patch(
        "aws_xray_sdk.core.patch_all",
        mock_patch_all,
    ), patch(
        "aws_xray_sdk.core.patch",
        mock_patch,
    ):
        tracing_mod.configure_xray()
        tracing_mod.configure_xray()

    mock_patch_all.assert_called_once_with()
    mock_patch.assert_not_called()
    assert tracing_mod.is_configured() is True
    assert tracing_mod.is_httplib_patched() is False


def test_configure_xray_patches_httplib_only_when_requested() -> None:
    mock_patch_all = MagicMock()
    mock_patch = MagicMock()
    with patch(
        "aws_xray_sdk.core.patch_all",
        mock_patch_all,
    ), patch(
        "aws_xray_sdk.core.patch",
        mock_patch,
    ):
        tracing_mod.configure_xray(patch_httplib=True)
        tracing_mod.configure_xray(patch_httplib=True)

    mock_patch_all.assert_called_once_with()
    mock_patch.assert_called_once_with(("httplib",), raise_errors=False)
    assert tracing_mod.is_httplib_patched() is True


def test_configure_xray_httplib_after_base_config() -> None:
    mock_patch_all = MagicMock()
    mock_patch = MagicMock()
    with patch(
        "aws_xray_sdk.core.patch_all",
        mock_patch_all,
    ), patch(
        "aws_xray_sdk.core.patch",
        mock_patch,
    ):
        tracing_mod.configure_xray()
        tracing_mod.configure_xray(patch_httplib=True)

    mock_patch_all.assert_called_once_with()
    mock_patch.assert_called_once_with(("httplib",), raise_errors=False)


def test_configure_xray_soft_fail_without_sdk() -> None:
    """Sin aws-xray-sdk instalado, configure_xray no lanza."""
    blocked = {
        name: None
        for name in list(sys.modules)
        if name == "aws_xray_sdk" or name.startswith("aws_xray_sdk.")
    }
    blocked.setdefault("aws_xray_sdk", None)
    blocked.setdefault("aws_xray_sdk.core", None)

    with patch.dict(sys.modules, blocked):
        tracing_mod.configure_xray(patch_httplib=True)

    assert tracing_mod.is_configured() is False
    assert tracing_mod.is_httplib_patched() is False
