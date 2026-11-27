"""Tests for the coordinator."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.tuya_project_cloud.api import (
    TuyaApiError,
    TuyaAuthenticationError,
    TuyaAuthorizationError,
    TuyaFunction,
    TuyaShadowProperty,
)
from custom_components.tuya_project_cloud.coordinator import (
    TuyaProjectCloudCoordinator,
)


def _make_coordinator(hass, entry) -> TuyaProjectCloudCoordinator:
    """Create a coordinator with a mocked client."""
    client = MagicMock()
    client.async_get_devices = AsyncMock(return_value=[])
    client.async_get_status = AsyncMock(return_value={})
    client.async_get_functions = AsyncMock(return_value={})
    client.async_get_specifications = AsyncMock(return_value={})
    client.async_get_thing_shadow = AsyncMock(return_value={})
    return TuyaProjectCloudCoordinator(hass, entry, client)


@pytest.mark.asyncio
async def test_empty_device_list(hass, mock_config_entry) -> None:
    """An empty device list yields an empty mapping."""
    coordinator = _make_coordinator(hass, mock_config_entry)
    assert await coordinator._async_update_data() == {}


@pytest.mark.asyncio
async def test_device_mapping(hass, mock_config_entry) -> None:
    """Devices are enriched with status and functions."""
    coordinator = _make_coordinator(hass, mock_config_entry)
    coordinator.client.async_get_devices = AsyncMock(
        return_value=[
            {
                "id": "dev1",
                "name": "Plug",
                "category": "cz",
                "product_id": "p1",
                "online": True,
                "uid": "u1",
                "owner_id": "h1",
            }
        ]
    )
    coordinator.client.async_get_status = AsyncMock(return_value={"switch": True})
    coordinator.client.async_get_functions = AsyncMock(
        return_value={"switch": TuyaFunction(code="switch", type="Boolean")}
    )
    coordinator.client.async_get_specifications = AsyncMock(return_value={})
    data = await coordinator._async_update_data()
    assert "dev1" in data
    assert data["dev1"].status == {"switch": True}
    assert "switch" in data["dev1"].functions


@pytest.mark.asyncio
async def test_auth_error_starts_reauth(hass, mock_config_entry) -> None:
    """Auth errors are surfaced as ConfigEntryAuthFailed."""
    coordinator = _make_coordinator(hass, mock_config_entry)
    coordinator.client.async_get_devices = AsyncMock(
        side_effect=TuyaAuthenticationError("bad")
    )
    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


@pytest.mark.asyncio
async def test_api_error_becomes_update_failed(hass, mock_config_entry) -> None:
    """API errors are surfaced as UpdateFailed."""
    coordinator = _make_coordinator(hass, mock_config_entry)
    coordinator.client.async_get_devices = AsyncMock(side_effect=TuyaApiError("bad"))
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


@pytest.mark.asyncio
async def test_send_command_refreshes(hass, mock_config_entry) -> None:
    """Sending a command triggers a refresh."""
    coordinator = _make_coordinator(hass, mock_config_entry)
    coordinator.async_request_refresh = AsyncMock()
    coordinator.client.async_send_command = AsyncMock()
    await coordinator.async_send_command("dev1", "switch", True)
    coordinator.client.async_send_command.assert_awaited_once()
    coordinator.async_request_refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_shadow_is_loaded_once(hass, mock_config_entry) -> None:
    """Thing shadow data is fetched once and kept on the device."""
    coordinator = _make_coordinator(hass, mock_config_entry)
    coordinator.client.async_get_devices = AsyncMock(
        return_value=[
            {
                "id": "dev1",
                "name": "Charger",
                "category": "dj",
                "product_id": "p1",
                "online": True,
            }
        ]
    )
    shadow = {"x_work_state": TuyaShadowProperty(code="x_work_state", value="300")}
    coordinator.client.async_get_thing_shadow = AsyncMock(return_value=shadow)
    await coordinator._async_update_data()
    await coordinator._async_update_data()
    coordinator.client.async_get_thing_shadow.assert_awaited_once_with("dev1")


@pytest.mark.asyncio
async def test_iot_core_authorization_issue(hass, mock_config_entry) -> None:
    """Missing IoT Core authorization is tracked for repairs."""
    coordinator = _make_coordinator(hass, mock_config_entry)
    coordinator.client.async_get_devices = AsyncMock(
        return_value=[
            {
                "id": "dev1",
                "name": "Charger",
                "category": "dj",
                "product_id": "p1",
                "online": True,
            }
        ]
    )
    coordinator.client.async_get_thing_shadow = AsyncMock(
        side_effect=TuyaAuthorizationError("not authorized", code=28841105)
    )
    await coordinator._async_update_data()
    assert coordinator.iot_core_not_authorized is True
