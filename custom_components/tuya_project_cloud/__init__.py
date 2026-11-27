"""The Tuya Project Cloud integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    TuyaApiError,
    TuyaAuthenticationError,
    TuyaOpenApi,
)
from .const import (
    CONF_ACCESS_ID,
    CONF_ACCESS_SECRET,
    CONF_REGION,
    ISSUE_API_NOT_AUTHORIZED,
    ISSUE_COMMAND_NOT_AUTHORIZED,
    ISSUE_IOT_CORE_NOT_AUTHORIZED,
    ISSUE_REGION_MISMATCH,
    PLATFORMS,
)
from .const import (
    DOMAIN as DOMAIN,
)
from .coordinator import TuyaProjectCloudCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Tuya Project Cloud from a config entry."""
    client = TuyaOpenApi(
        async_get_clientsession(hass),
        entry.data[CONF_ACCESS_ID],
        entry.data[CONF_ACCESS_SECRET],
        entry.data[CONF_REGION],
    )
    coordinator = TuyaProjectCloudCoordinator(hass, entry, client)
    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryAuthFailed:
        raise
    except TuyaAuthenticationError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except (TuyaApiError, OSError) as err:
        # Authorization and transient API errors must not become an
        # unhandled exception during setup; retrying is always safer.
        raise ConfigEntryNotReady(str(err)) from err

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(
        entry, [Platform(platform) for platform in PLATFORMS]
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(
        entry, [Platform(platform) for platform in PLATFORMS]
    )


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove repairs that belong to a deleted config entry."""
    for issue in (
        ISSUE_API_NOT_AUTHORIZED,
        ISSUE_COMMAND_NOT_AUTHORIZED,
        ISSUE_IOT_CORE_NOT_AUTHORIZED,
        ISSUE_REGION_MISMATCH,
    ):
        ir.async_delete_issue(hass, DOMAIN, f"{entry.entry_id}_{issue}")
