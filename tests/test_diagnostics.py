"""Tests for diagnostics redaction."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.tuya_project_cloud.api import TuyaDevice, TuyaShadowProperty
from custom_components.tuya_project_cloud.diagnostics import (
    _redact,
    async_get_config_entry_diagnostics,
)


def test_redact_nested() -> None:
    """Sensitive keys are redacted recursively."""
    data = {
        "access_token": "secret",
        "local_key": "secret",
        "uid": "secret",
        "stream_url": "https://example.invalid/live.m3u8",
        "nested": [{"access_secret": "secret", "m3u8": "url", "safe": "value"}],
    }
    result = _redact(data)
    assert result["access_token"] == "**REDACTED**"
    assert result["stream_url"] == "**REDACTED**"
    assert result["nested"][0]["access_secret"] == "**REDACTED**"
    assert result["nested"][0]["m3u8"] == "**REDACTED**"
    assert result["nested"][0]["safe"] == "value"


@pytest.mark.asyncio
async def test_entry_diagnostics(hass, mock_config_entry) -> None:
    """Entry diagnostics never contain credentials."""
    coordinator = MagicMock()
    coordinator.data = {
        "dev1": TuyaDevice(
            id="dev1",
            name="Test",
            category="cz",
            product_id="p",
            online=True,
            shadow={"x_work_state": TuyaShadowProperty("x_work_state", "300")},
        )
    }
    coordinator.last_update_success = True
    coordinator.api_not_authorized = False
    coordinator.iot_core_not_authorized = False
    mock_config_entry.runtime_data = coordinator
    result = await async_get_config_entry_diagnostics(hass, mock_config_entry)
    text = str(result)
    assert "test_access_secret" not in text
    assert "test_access_id" not in text
    assert result["device_count"] == 1
    assert result["devices"][0]["shadow_codes"] == ["x_work_state"]
    assert "300" not in text
