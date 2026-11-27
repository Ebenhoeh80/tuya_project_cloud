"""Tests for integration setup and unload."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import ConfigEntryAuthFailed

from custom_components.tuya_project_cloud.api import (
    TuyaConnectionError,
)


@pytest.mark.asyncio
async def test_setup_entry_success(hass, mock_config_entry) -> None:
    """A successful setup stores the coordinator in runtime_data."""
    mock_config_entry.add_to_hass(hass)
    coordinator = MagicMock()
    coordinator.async_config_entry_first_refresh = AsyncMock()
    forward = AsyncMock()
    with (
        patch(
            "custom_components.tuya_project_cloud.TuyaOpenApi",
            return_value=MagicMock(),
        ),
        patch(
            "custom_components.tuya_project_cloud.TuyaProjectCloudCoordinator",
            return_value=coordinator,
        ),
        patch.object(hass.config_entries, "async_forward_entry_setups", forward),
    ):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert mock_config_entry.runtime_data is coordinator
    forwarded = {str(platform) for platform in forward.call_args.args[1]}
    assert "camera" in forwarded


@pytest.mark.asyncio
async def test_setup_auth_failed(hass, mock_config_entry) -> None:
    """Auth errors become ConfigEntryAuthFailed."""
    mock_config_entry.add_to_hass(hass)
    coordinator = MagicMock()
    coordinator.async_config_entry_first_refresh = AsyncMock(
        side_effect=ConfigEntryAuthFailed("bad")
    )
    with (
        patch(
            "custom_components.tuya_project_cloud.TuyaOpenApi", return_value=MagicMock()
        ),
        patch(
            "custom_components.tuya_project_cloud.TuyaProjectCloudCoordinator",
            return_value=coordinator,
        ),
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR


@pytest.mark.asyncio
async def test_setup_not_ready(hass, mock_config_entry) -> None:
    """Connection errors become ConfigEntryNotReady."""
    mock_config_entry.add_to_hass(hass)
    coordinator = MagicMock()
    coordinator.async_config_entry_first_refresh = AsyncMock(
        side_effect=TuyaConnectionError("offline")
    )
    with (
        patch(
            "custom_components.tuya_project_cloud.TuyaOpenApi", return_value=MagicMock()
        ),
        patch(
            "custom_components.tuya_project_cloud.TuyaProjectCloudCoordinator",
            return_value=coordinator,
        ),
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY
