"""Tests for diagnostics redaction."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.tuya_project_cloud.api import (
    TuyaDevice,
    TuyaFunction,
    TuyaShadowProperty,
)
from custom_components.tuya_project_cloud.const import DOMAIN, TUYA_DEVICE_DOMAIN
from custom_components.tuya_project_cloud.diagnostics import (
    _redact,
    async_get_config_entry_diagnostics,
    async_get_device_diagnostics,
)
from custom_components.tuya_project_cloud.utils import redact_identifier


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
    assert result["devices"][0]["last_update_success"] is True
    assert result["devices"][0]["shadow_last_update_success"] is True
    assert result["devices"][0]["shadow_codes"] == ["x_work_state"]
    assert "300" not in text
    assert result["devices"][0]["id"] == redact_identifier("dev1")
    assert "dev1" not in text
    assert result["scan_interval"] == 30
    assert result["scan_interval_unit"] == "seconds"
    assert result["enable_shadow"] is True
    assert result["enable_camera"] is True


@pytest.mark.asyncio
async def test_device_diagnostics_pseudonymizes_id(hass, mock_config_entry) -> None:
    """Device diagnostics keep useful codes without exposing the Tuya ID."""
    coordinator = MagicMock()
    coordinator.data = {
        "dev-secret-123": TuyaDevice(
            id="dev-secret-123",
            name="Plug",
            category="cz",
            product_id="p1",
            online=True,
            status={"stream_url": "https://example.invalid/live.m3u8"},
            functions={"switch": MagicMock(type="Boolean", values={})},
        )
    }
    mock_config_entry.runtime_data = coordinator
    device = MagicMock()
    device.identifiers = {
        (DOMAIN, "dev-secret-123"),
        (TUYA_DEVICE_DOMAIN, "dev-secret-123"),
    }
    result = await async_get_device_diagnostics(hass, mock_config_entry, device)
    text = str(result)
    assert "dev-secret-123" not in text
    assert "https://example.invalid/live.m3u8" not in text
    assert result["device_id"] == redact_identifier("dev-secret-123")
    assert result["status"] == {"stream_url": "**REDACTED**"}
    assert result["functions"]["switch"]["type"] == "Boolean"


@pytest.mark.asyncio
async def test_device_diagnostics_unknown_identifier_is_safe(
    hass, mock_config_entry
) -> None:
    """An unrelated device identifier yields an empty, safe payload."""
    coordinator = MagicMock()
    coordinator.data = {}
    mock_config_entry.runtime_data = coordinator
    device = MagicMock()
    device.identifiers = {("other_domain", "dev1")}
    result = await async_get_device_diagnostics(hass, mock_config_entry, device)
    assert result["device_id"] is None
    assert result["status"] == {}
    assert result["functions"] == {}


@pytest.mark.asyncio
async def test_device_diagnostics_omit_specification_metadata(
    hass, mock_config_entry
) -> None:
    """Specification details used for scaling never enter diagnostics."""
    coordinator = MagicMock()
    coordinator.data = {
        "dev1": TuyaDevice(
            id="dev1",
            name="Meter",
            category="cz",
            product_id="p1",
            online=True,
            status={"cur_power": 37},
            specifications={
                "cur_power": TuyaFunction(
                    "cur_power",
                    "Integer",
                    {
                        "scale": 1,
                        "min": 987654,
                        "max": 987655,
                        "unit": "MARKER_UNIT_XYZ",
                    },
                )
            },
        )
    }
    mock_config_entry.runtime_data = coordinator
    device = MagicMock()
    device.identifiers = {(DOMAIN, "dev1")}
    result = await async_get_device_diagnostics(hass, mock_config_entry, device)
    text = str(result)
    assert result["status"] == {"cur_power": 37}
    assert "MARKER_UNIT_XYZ" not in text
    assert "987654" not in text
    assert "987655" not in text
