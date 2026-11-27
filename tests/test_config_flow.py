"""Tests for the config flow."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import SOURCE_REAUTH
from homeassistant.data_entry_flow import FlowResultType

from custom_components.tuya_project_cloud.const import (
    CONF_ACCESS_ID,
    CONF_ACCESS_SECRET,
    CONF_REGION,
)

USER_INPUT = {
    CONF_ACCESS_ID: "test_access_id",
    CONF_ACCESS_SECRET: "secret",
    CONF_REGION: "eu",
}


@pytest.mark.asyncio
async def test_user_flow_success(hass) -> None:
    """A valid project creates an entry without app credentials."""
    result = await hass.config_entries.flow.async_init(
        "tuya_project_cloud", context={"source": "user"}
    )
    assert result["type"] is FlowResultType.FORM
    with patch(
        "custom_components.tuya_project_cloud.config_flow.TuyaOpenApi.async_validate",
        AsyncMock(),
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )
    assert result2["type"] is FlowResultType.CREATE_ENTRY
    assert result2["data"] == USER_INPUT
    assert "password" not in result2["data"]


@pytest.mark.asyncio
async def test_user_flow_invalid_auth(hass) -> None:
    """Invalid credentials show an error."""
    from custom_components.tuya_project_cloud.api import TuyaAuthenticationError

    result = await hass.config_entries.flow.async_init(
        "tuya_project_cloud", context={"source": "user"}
    )
    with patch(
        "custom_components.tuya_project_cloud.config_flow.TuyaOpenApi.async_validate",
        AsyncMock(side_effect=TuyaAuthenticationError("bad")),
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )
    assert result2["type"] is FlowResultType.FORM
    assert result2["errors"] == {"base": "invalid_auth"}


@pytest.mark.asyncio
async def test_user_flow_duplicate(hass, mock_config_entry) -> None:
    """A second entry for the same access ID is rejected."""
    with patch(
        "custom_components.tuya_project_cloud.async_setup_entry",
        AsyncMock(return_value=True),
    ):
        mock_config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        "tuya_project_cloud", context={"source": "user"}
    )
    with patch(
        "custom_components.tuya_project_cloud.config_flow.TuyaOpenApi.async_validate",
        AsyncMock(),
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )
    assert result2["type"] is FlowResultType.ABORT
    assert result2["reason"] == "already_configured"


@pytest.mark.asyncio
async def test_options_flow(hass, mock_config_entry) -> None:
    """Options include shadow and camera toggles and reload the entry."""
    with patch(
        "custom_components.tuya_project_cloud.async_setup_entry",
        AsyncMock(return_value=True),
    ):
        mock_config_entry.add_to_hass(hass)
        result = await hass.config_entries.options.async_init(
            mock_config_entry.entry_id
        )
        assert result["type"] is FlowResultType.FORM
        result2 = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {"scan_interval": 60, "enable_shadow": True, "enable_camera": False},
        )
    assert result2["type"] is FlowResultType.CREATE_ENTRY
    assert result2["data"]["enable_camera"] is False
    assert result2["data"]["enable_shadow"] is True


@pytest.mark.asyncio
async def test_reauth_success_updates_credentials(hass, mock_config_entry) -> None:
    """Reauth updates the entry data and keeps the same unique ID."""
    with patch(
        "custom_components.tuya_project_cloud.async_setup_entry",
        AsyncMock(return_value=True),
    ):
        mock_config_entry.add_to_hass(hass)
        result = await hass.config_entries.flow.async_init(
            "tuya_project_cloud",
            context={
                "source": SOURCE_REAUTH,
                "entry_id": mock_config_entry.entry_id,
            },
            data=mock_config_entry.data,
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "reauth_confirm"
        updated = {**USER_INPUT, CONF_ACCESS_SECRET: "new_secret"}
        with patch(
            "custom_components.tuya_project_cloud.config_flow.TuyaOpenApi.async_validate",
            AsyncMock(),
        ):
            result2 = await hass.config_entries.flow.async_configure(
                result["flow_id"], updated
            )
    assert result2["type"] is FlowResultType.ABORT
    assert result2["reason"] == "reauth_successful"
    assert mock_config_entry.data[CONF_ACCESS_SECRET] == "new_secret"
    assert mock_config_entry.unique_id == "test_access_id"


@pytest.mark.asyncio
async def test_reauth_invalid_auth_keeps_old_data(hass, mock_config_entry) -> None:
    """A failed reauth shows the localized error and keeps the old credentials."""
    from custom_components.tuya_project_cloud.api import TuyaAuthenticationError

    with patch(
        "custom_components.tuya_project_cloud.async_setup_entry",
        AsyncMock(return_value=True),
    ):
        mock_config_entry.add_to_hass(hass)
        result = await hass.config_entries.flow.async_init(
            "tuya_project_cloud",
            context={
                "source": SOURCE_REAUTH,
                "entry_id": mock_config_entry.entry_id,
            },
            data=mock_config_entry.data,
        )
        with patch(
            "custom_components.tuya_project_cloud.config_flow.TuyaOpenApi.async_validate",
            AsyncMock(side_effect=TuyaAuthenticationError("bad")),
        ):
            result2 = await hass.config_entries.flow.async_configure(
                result["flow_id"], USER_INPUT
            )
    assert result2["type"] is FlowResultType.FORM
    assert result2["errors"] == {"base": "invalid_auth"}
    assert mock_config_entry.data[CONF_ACCESS_SECRET] == "test_access_secret"


def test_region_title_is_localized() -> None:
    """Config entry titles use readable region names, not raw codes."""
    from custom_components.tuya_project_cloud.config_flow import _region_title

    assert _region_title("de-DE", "eu") == "Tuya Cloud (Europa (Zentral))"
    assert _region_title("en", "us_east") == "Tuya Cloud (United States (East))"


@pytest.mark.asyncio
async def test_options_flow_defaults(hass, mock_config_entry) -> None:
    """Empty options fall back to the documented defaults."""
    with patch(
        "custom_components.tuya_project_cloud.async_setup_entry",
        AsyncMock(return_value=True),
    ):
        mock_config_entry.add_to_hass(hass)
        result = await hass.config_entries.options.async_init(
            mock_config_entry.entry_id
        )
    assert result["type"] is FlowResultType.FORM
    defaults = result["data_schema"]({})
    assert defaults["scan_interval"] == 30
    assert defaults["enable_shadow"] is True
    assert defaults["enable_camera"] is True
