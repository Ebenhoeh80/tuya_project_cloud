"""Tests for the coordinator."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    HomeAssistantError,
    ServiceValidationError,
)
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.tuya_project_cloud.api import (
    TuyaApiError,
    TuyaAuthenticationError,
    TuyaAuthorizationError,
    TuyaConnectionError,
    TuyaFunction,
    TuyaShadowProperty,
    TuyaUnsupportedError,
)
from custom_components.tuya_project_cloud.coordinator import (
    TuyaProjectCloudCoordinator,
)
from custom_components.tuya_project_cloud.utils import redact_identifier


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
async def test_shadow_is_throttled_within_refresh_interval(
    hass, mock_config_entry
) -> None:
    """Repeated polls inside the refresh interval reuse the shadow."""
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


@pytest.mark.asyncio
async def test_shadow_is_retried_while_empty(hass, mock_config_entry) -> None:
    """An offline/empty shadow is retried on the next poll."""
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
    coordinator.client.async_get_thing_shadow = AsyncMock(side_effect=[{}, shadow])
    first = await coordinator._async_update_data()
    assert first["dev1"].shadow == {}
    # Simulate the refresh interval having elapsed.
    coordinator._last_shadow_refresh["dev1"] = 0.0
    second = await coordinator._async_update_data()
    assert second["dev1"].shadow == shadow
    assert coordinator.client.async_get_thing_shadow.await_count == 2


@pytest.mark.asyncio
async def test_shadow_updates_after_interval(hass, mock_config_entry) -> None:
    """Charger shadow values are refreshed instead of freezing at startup."""
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
    first_shadow = {
        "x_work_state": TuyaShadowProperty(code="x_work_state", value="300")
    }
    second_shadow = {
        "x_work_state": TuyaShadowProperty(code="x_work_state", value="301")
    }
    coordinator.client.async_get_thing_shadow = AsyncMock(
        side_effect=[first_shadow, second_shadow]
    )
    first = await coordinator._async_update_data()
    assert first["dev1"].shadow["x_work_state"].value == "300"
    coordinator._last_shadow_refresh["dev1"] = 0.0
    second = await coordinator._async_update_data()
    assert second["dev1"].shadow["x_work_state"].value == "301"


@pytest.mark.asyncio
async def test_failed_device_read_marks_data_stale(hass, mock_config_entry) -> None:
    """Repeated read failures mark the device data as stale."""
    coordinator = _make_coordinator(hass, mock_config_entry)
    coordinator.client.async_get_devices = AsyncMock(
        return_value=[
            {
                "id": "dev1",
                "name": "Plug",
                "category": "cz",
                "product_id": "p1",
                "online": True,
            }
        ]
    )
    coordinator.client.async_get_status = AsyncMock(
        side_effect=[{"switch": True}, TuyaApiError("offline")]
    )
    first = await coordinator._async_update_data()
    assert first["dev1"].last_update_success is True
    second = await coordinator._async_update_data()
    assert second["dev1"].last_update_success is False
    assert second["dev1"].status == {"switch": True}


@pytest.mark.asyncio
async def test_unsupported_legacy_status_is_not_a_failure(
    hass, mock_config_entry
) -> None:
    """IoT Core-only devices stay successful though legacy endpoints reject them."""
    coordinator = _make_coordinator(hass, mock_config_entry)
    coordinator.client.async_get_devices = AsyncMock(
        return_value=[
            {
                "id": "dev2",
                "name": "Charger",
                "category": "dj",
                "product_id": "p2",
                "online": True,
            }
        ]
    )
    coordinator.client.async_get_status = AsyncMock(
        side_effect=TuyaUnsupportedError("function not support", code=2003)
    )
    coordinator.client.async_get_functions = AsyncMock(
        side_effect=TuyaUnsupportedError("not support this device", code=2009)
    )
    coordinator.client.async_get_specifications = AsyncMock(
        side_effect=TuyaUnsupportedError("function not support", code=2003)
    )
    coordinator.client.async_get_thing_shadow = AsyncMock(
        return_value={"x_work_state": TuyaShadowProperty("x_work_state", "101", 101, 1)}
    )
    data = await coordinator._async_update_data()
    assert data["dev2"].last_update_success is True
    assert data["dev2"].status == {}
    assert "x_work_state" in data["dev2"].shadow
    assert data["dev2"].shadow_last_update_success is True
    assert coordinator.api_not_authorized is False
    assert coordinator.iot_core_not_authorized is False


@pytest.mark.asyncio
async def test_shadow_failure_keeps_device_available_but_marks_shadow_stale(
    hass, mock_config_entry
) -> None:
    """A shadow error after an unsupported status must not pretend fresh data."""
    coordinator = _make_coordinator(hass, mock_config_entry)
    coordinator.client.async_get_devices = AsyncMock(
        return_value=[
            {
                "id": "dev2",
                "name": "Charger",
                "category": "dj",
                "product_id": "p2",
                "online": True,
            }
        ]
    )
    coordinator.client.async_get_status = AsyncMock(
        side_effect=TuyaUnsupportedError("function not support", code=2003)
    )
    coordinator.client.async_get_functions = AsyncMock(return_value={})
    coordinator.client.async_get_specifications = AsyncMock(return_value={})
    coordinator.client.async_get_thing_shadow = AsyncMock(
        side_effect=TuyaConnectionError("timeout")
    )
    data = await coordinator._async_update_data()
    assert data["dev2"].last_update_success is True
    assert data["dev2"].shadow == {}
    assert data["dev2"].shadow_last_update_success is False


@pytest.mark.asyncio
async def test_shadow_authorization_error_still_raises_iot_core_issue(
    hass, mock_config_entry
) -> None:
    """Unsupported legacy status must not hide a missing IoT Core permission."""
    coordinator = _make_coordinator(hass, mock_config_entry)
    coordinator.client.async_get_devices = AsyncMock(
        return_value=[
            {
                "id": "dev2",
                "name": "Charger",
                "category": "dj",
                "product_id": "p2",
                "online": True,
            }
        ]
    )
    coordinator.client.async_get_status = AsyncMock(
        side_effect=TuyaUnsupportedError("function not support", code=2003)
    )
    coordinator.client.async_get_functions = AsyncMock(
        side_effect=TuyaUnsupportedError("not support this device", code=2009)
    )
    coordinator.client.async_get_specifications = AsyncMock(return_value={})
    coordinator.client.async_get_thing_shadow = AsyncMock(
        side_effect=TuyaAuthorizationError("not authorized", code=28841105)
    )
    with patch(
        "custom_components.tuya_project_cloud.coordinator.async_update_issues"
    ) as update_issues:
        data = await coordinator._async_update_data()
    assert data["dev2"].shadow_last_update_success is False
    assert coordinator.api_not_authorized is False
    assert coordinator.iot_core_not_authorized is True
    update_issues.assert_called_once()


@pytest.mark.asyncio
async def test_unsupported_functions_after_successful_status(
    hass, mock_config_entry
) -> None:
    """Errno 2009 for functions alone must not mark a healthy device as stale."""
    coordinator = _make_coordinator(hass, mock_config_entry)
    coordinator.client.async_get_devices = AsyncMock(
        return_value=[
            {
                "id": "dev1",
                "name": "Plug",
                "category": "cz",
                "product_id": "p1",
                "online": True,
            }
        ]
    )
    coordinator.client.async_get_status = AsyncMock(return_value={"switch": True})
    coordinator.client.async_get_functions = AsyncMock(
        side_effect=TuyaUnsupportedError("not support this device", code=2009)
    )
    coordinator.client.async_get_specifications = AsyncMock(return_value={})
    data = await coordinator._async_update_data()
    assert data["dev1"].last_update_success is True
    assert data["dev1"].status == {"switch": True}


@pytest.mark.asyncio
async def test_issues_are_written_only_on_state_change(hass, mock_config_entry) -> None:
    """Repeated identical polls do not rewrite the issue registry."""
    coordinator = _make_coordinator(hass, mock_config_entry)
    with patch(
        "custom_components.tuya_project_cloud.coordinator.async_update_issues"
    ) as update_issues:
        await coordinator._async_update_data()
        await coordinator._async_update_data()
        update_issues.assert_called_once()
        coordinator.client.async_get_devices = AsyncMock(
            return_value=[
                {
                    "id": "dev2",
                    "name": "Plug",
                    "category": "cz",
                    "product_id": "p2",
                    "online": True,
                }
            ]
        )
        await coordinator._async_update_data()
        assert update_issues.call_count == 2


@pytest.mark.asyncio
async def test_denied_command_creates_repair_and_localized_error(
    hass, mock_config_entry
) -> None:
    """Error 1106 becomes a repair and a translatable service error."""
    coordinator = _make_coordinator(hass, mock_config_entry)
    coordinator.async_request_refresh = AsyncMock()
    coordinator.client.async_send_command = AsyncMock(
        side_effect=TuyaAuthorizationError("denied", code=1106)
    )
    with (
        patch(
            "custom_components.tuya_project_cloud.coordinator.async_update_command_issue"
        ) as update_issue,
        pytest.raises(ServiceValidationError) as err,
    ):
        await coordinator.async_send_command("dev1", "switch", True)
    assert err.value.translation_key == "command_not_authorized"
    assert err.value.translation_domain == "tuya_project_cloud"
    update_issue.assert_called_once_with(
        hass, mock_config_entry.entry_id, not_authorized=True
    )
    coordinator.async_request_refresh.assert_not_awaited()


@pytest.mark.asyncio
async def test_successful_command_clears_repair(hass, mock_config_entry) -> None:
    """A successful command clears an earlier authorization repair."""
    coordinator = _make_coordinator(hass, mock_config_entry)
    coordinator.async_request_refresh = AsyncMock()
    coordinator.client.async_send_command = AsyncMock()
    with patch(
        "custom_components.tuya_project_cloud.coordinator.async_update_command_issue"
    ) as update_issue:
        await coordinator.async_send_command("dev1", "switch", True)
    update_issue.assert_called_once_with(
        hass, mock_config_entry.entry_id, not_authorized=False
    )
    coordinator.async_request_refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_partial_device_error_keeps_device(hass, mock_config_entry) -> None:
    """A failed device read keeps the device but does not break the update."""
    coordinator = _make_coordinator(hass, mock_config_entry)
    coordinator.client.async_get_devices = AsyncMock(
        return_value=[
            {
                "id": "dev1",
                "name": "Plug",
                "category": "cz",
                "product_id": "p1",
                "online": True,
            }
        ]
    )
    coordinator.client.async_get_status = AsyncMock(side_effect=TuyaApiError("bad"))
    data = await coordinator._async_update_data()
    assert data["dev1"].name == "Plug"
    assert data["dev1"].status == {}


@pytest.mark.asyncio
async def test_log_messages_do_not_contain_raw_device_id(
    hass, mock_config_entry, caplog
) -> None:
    """Debug logs use a pseudonym instead of the Tuya device ID."""
    coordinator = _make_coordinator(hass, mock_config_entry)
    coordinator.client.async_get_devices = AsyncMock(
        return_value=[
            {
                "id": "dev-secret-123",
                "name": "Plug",
                "category": "cz",
                "product_id": "p1",
                "online": True,
            }
        ]
    )
    coordinator.client.async_get_status = AsyncMock(side_effect=TuyaApiError("bad"))
    with caplog.at_level("DEBUG"):
        await coordinator._async_update_data()
    assert "dev-secret-123" not in caplog.text
    assert redact_identifier("dev-secret-123") in caplog.text


@pytest.mark.asyncio
async def test_debug_logs_keep_error_code_without_raw_message(
    hass, mock_config_entry, caplog
) -> None:
    """Debug logs stay useful without echoing the raw API message."""
    coordinator = _make_coordinator(hass, mock_config_entry)
    coordinator.client.async_get_devices = AsyncMock(
        return_value=[
            {
                "id": "dev-secret-123",
                "name": "Plug",
                "category": "cz",
                "product_id": "p1",
                "online": True,
            }
        ]
    )
    coordinator.client.async_get_status = AsyncMock(
        side_effect=TuyaAuthorizationError("raw-secret-message", code=1106)
    )
    with caplog.at_level("DEBUG"):
        await coordinator._async_update_data()
    assert "code=1106" in caplog.text
    assert "raw-secret-message" not in caplog.text


@pytest.mark.asyncio
async def test_device_list_errors_are_localized_without_raw_details(
    hass, mock_config_entry
) -> None:
    """Fetch failures use translation keys instead of raw API messages."""
    coordinator = _make_coordinator(hass, mock_config_entry)
    coordinator.client.async_get_devices = AsyncMock(
        side_effect=TuyaAuthenticationError("secret-token-value")
    )
    with pytest.raises(ConfigEntryAuthFailed) as auth_err:
        await coordinator._async_update_data()
    assert auth_err.value.translation_key == "authentication_failed"
    assert auth_err.value.translation_domain == "tuya_project_cloud"
    assert "secret-token-value" not in str(auth_err.value)

    coordinator.client.async_get_devices = AsyncMock(
        side_effect=TuyaApiError("secret-endpoint-value")
    )
    with pytest.raises(UpdateFailed) as update_err:
        await coordinator._async_update_data()
    assert update_err.value.translation_key == "update_failed"
    assert update_err.value.translation_domain == "tuya_project_cloud"
    assert "secret-endpoint-value" not in str(update_err.value)


@pytest.mark.asyncio
async def test_missing_device_name_uses_readable_fallback(
    hass, mock_config_entry
) -> None:
    """An unnamed device never exposes its internal ID as the display name."""
    coordinator = _make_coordinator(hass, mock_config_entry)
    coordinator.client.async_get_devices = AsyncMock(
        return_value=[
            {
                "id": "dev-secret-123",
                "name": "   ",
                "category": "cz",
                "product_id": "p1",
                "online": True,
            }
        ]
    )
    data = await coordinator._async_update_data()
    assert data["dev-secret-123"].name == "Tuya device"

    hass.config.language = "de"
    coordinator.client.async_get_devices = AsyncMock(
        return_value=[
            {
                "id": "dev-secret-456",
                "category": "cz",
                "product_id": "p1",
                "online": True,
            }
        ]
    )
    data = await coordinator._async_update_data()
    assert data["dev-secret-456"].name == "Tuya-Gerät"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        TuyaAuthorizationError("denied", code=1234),
        TuyaApiError("secret-detail"),
    ],
)
async def test_other_command_errors_are_localized(
    hass, mock_config_entry, error
) -> None:
    """Non-1106 command failures are friendly and do not create a repair."""
    coordinator = _make_coordinator(hass, mock_config_entry)
    coordinator.async_request_refresh = AsyncMock()
    coordinator.client.async_send_command = AsyncMock(side_effect=error)
    with (
        patch(
            "custom_components.tuya_project_cloud.coordinator.async_update_command_issue"
        ) as update_issue,
        pytest.raises(HomeAssistantError) as err,
    ):
        await coordinator.async_send_command("dev1", "switch", True)
    assert err.value.translation_key == "command_failed"
    assert err.value.translation_domain == "tuya_project_cloud"
    assert "secret-detail" not in str(err.value)
    update_issue.assert_not_called()
    coordinator.async_request_refresh.assert_not_awaited()
