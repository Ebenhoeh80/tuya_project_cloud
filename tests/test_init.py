"""Tests for integration setup and unload."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from custom_components.tuya_project_cloud import async_remove_entry, async_setup_entry
from custom_components.tuya_project_cloud.api import (
    TuyaApiError,
    TuyaAuthenticationError,
    TuyaAuthorizationError,
    TuyaConnectionError,
)


@pytest.fixture
def suppress_reauth(hass):
    """Keep the automatic reauth flow from outliving an auth-failure test."""
    with patch.object(
        hass.config_entries.flow,
        "async_init",
        AsyncMock(return_value={"type": "abort", "reason": "already_configured"}),
    ):
        yield


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
async def test_setup_auth_failed(hass, mock_config_entry, suppress_reauth) -> None:
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


@pytest.mark.asyncio
async def test_remove_entry_deletes_issues(hass, mock_config_entry) -> None:
    """Deleting a config entry also removes its repairs."""
    with patch(
        "custom_components.tuya_project_cloud.ir.async_delete_issue"
    ) as delete_issue:
        await async_remove_entry(hass, mock_config_entry)
    assert delete_issue.call_count == 4
    assert all(
        call.args[1] == "tuya_project_cloud" for call in delete_issue.call_args_list
    )


@pytest.mark.asyncio
async def test_setup_authorization_error_retries(hass, mock_config_entry) -> None:
    """An authorization error during setup must not become an unhandled error."""
    mock_config_entry.add_to_hass(hass)
    coordinator = MagicMock()
    coordinator.async_config_entry_first_refresh = AsyncMock(
        side_effect=TuyaAuthorizationError("denied")
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


@pytest.mark.asyncio
async def test_unload_entry_unloads_every_platform(hass, mock_config_entry) -> None:
    """Unloading removes all forwarded platforms."""
    with patch.object(
        hass.config_entries, "async_unload_platforms", AsyncMock(return_value=True)
    ) as unload:
        from custom_components.tuya_project_cloud import async_unload_entry

        assert await async_unload_entry(hass, mock_config_entry) is True
    platforms = {str(platform) for platform in unload.call_args.args[1]}
    assert platforms == {
        "camera",
        "climate",
        "cover",
        "light",
        "number",
        "sensor",
        "switch",
    }


@pytest.mark.asyncio
async def test_unload_entry_forgets_camera_proxy_routes(
    hass, mock_config_entry
) -> None:
    """A successful unload removes stale proxy routes for this entry."""
    from custom_components.tuya_project_cloud import async_unload_entry
    from custom_components.tuya_project_cloud.stream_proxy import TuyaStreamProxy

    coordinator = MagicMock()
    mock_config_entry.runtime_data = coordinator
    proxy = MagicMock(spec=TuyaStreamProxy)
    hass.data.setdefault("tuya_project_cloud", {})["stream_proxy"] = proxy
    with patch.object(
        hass.config_entries, "async_unload_platforms", AsyncMock(return_value=True)
    ):
        assert await async_unload_entry(hass, mock_config_entry) is True
    proxy.unregister_coordinator.assert_called_once_with(coordinator)


@pytest.mark.asyncio
async def test_setup_errors_use_localized_keys(hass, mock_config_entry) -> None:
    """Setup failures never pass raw API text into the UI."""
    coordinator = MagicMock()
    coordinator.async_config_entry_first_refresh = AsyncMock(
        side_effect=TuyaAuthenticationError("secret-value")
    )
    with (
        patch(
            "custom_components.tuya_project_cloud.TuyaOpenApi", return_value=MagicMock()
        ),
        patch(
            "custom_components.tuya_project_cloud.TuyaProjectCloudCoordinator",
            return_value=coordinator,
        ),
        pytest.raises(ConfigEntryAuthFailed) as auth_err,
    ):
        await async_setup_entry(hass, mock_config_entry)
    assert auth_err.value.translation_key == "authentication_failed"
    assert "secret-value" not in str(auth_err.value)

    coordinator.async_config_entry_first_refresh = AsyncMock(
        side_effect=TuyaApiError("secret-value")
    )
    with (
        patch(
            "custom_components.tuya_project_cloud.TuyaOpenApi", return_value=MagicMock()
        ),
        patch(
            "custom_components.tuya_project_cloud.TuyaProjectCloudCoordinator",
            return_value=coordinator,
        ),
        pytest.raises(ConfigEntryNotReady) as retry_err,
    ):
        await async_setup_entry(hass, mock_config_entry)
    assert retry_err.value.translation_key == "setup_failed"
    assert "secret-value" not in str(retry_err.value)
