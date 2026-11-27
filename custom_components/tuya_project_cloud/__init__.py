"""The Tuya Project Cloud integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    TuyaAuthenticationError,
    TuyaConnectionError,
    TuyaOpenApi,
)
from .const import (
    CONF_ACCESS_ID,
    CONF_ACCESS_SECRET,
    CONF_REGION,
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
    except (TuyaConnectionError, OSError) as err:
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
