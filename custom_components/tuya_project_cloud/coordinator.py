"""DataUpdateCoordinator for Tuya Project Cloud."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    TuyaApiError,
    TuyaAuthenticationError,
    TuyaAuthorizationError,
    TuyaConnectionError,
    TuyaDevice,
    TuyaOpenApi,
)
from .const import (
    CONF_ENABLE_SHADOW,
    CONF_SCAN_INTERVAL,
    DEFAULT_ENABLE_SHADOW,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    ERR_API_NOT_AUTHORIZED,
)

_LOGGER = logging.getLogger(__name__)

type TuyaProjectCloudConfigEntry = ConfigEntry[TuyaProjectCloudCoordinator]


class TuyaProjectCloudCoordinator(DataUpdateCoordinator[dict[str, TuyaDevice]]):
    """Poll devices and their DPS status from the Tuya OpenAPI."""

    config_entry: TuyaProjectCloudConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: TuyaProjectCloudConfigEntry,
        client: TuyaOpenApi,
    ) -> None:
        """Initialize the coordinator."""
        interval = entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL.total_seconds()
        )
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=timedelta(seconds=interval),
        )
        self.client = client
        self._known: dict[str, TuyaDevice] = {}
        self.api_not_authorized = False
        self.iot_core_not_authorized = False
        self._shadow_loaded: set[str] = set()
        self._enable_shadow = bool(
            entry.options.get(CONF_ENABLE_SHADOW, DEFAULT_ENABLE_SHADOW)
        )

    async def _async_update_data(self) -> dict[str, TuyaDevice]:
        """Fetch devices, functions and status."""
        try:
            raw_devices = await self.client.async_get_devices()
        except TuyaAuthenticationError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except (TuyaApiError, TuyaConnectionError) as err:
            raise UpdateFailed(f"Cannot fetch devices: {err}") from err

        devices: dict[str, TuyaDevice] = {}
        for raw in raw_devices:
            device_id = raw.get("id")
            if not device_id:
                continue
            device = self._known.get(device_id) or TuyaDevice(
                id=device_id,
                name=str(raw.get("name", device_id)),
                category=str(raw.get("category", "")),
                product_id=str(raw.get("product_id", "")),
                online=bool(raw.get("online", False)),
                uid=str(raw.get("uid", "")),
                owner_id=str(raw.get("owner_id", "")),
            )
            device.name = str(raw.get("name", device.name))
            device.online = bool(raw.get("online", device.online))
            try:
                device.status = await self.client.async_get_status(device_id)
                if not device.functions:
                    device.functions = await self.client.async_get_functions(device_id)
                if not device.specifications:
                    device.specifications = await self.client.async_get_specifications(
                        device_id
                    )
                self.api_not_authorized = False
            except TuyaAuthorizationError as err:
                if err.code == ERR_API_NOT_AUTHORIZED:
                    self.api_not_authorized = True
                _LOGGER.debug("No API permission for device %s: %s", device_id, err)
            except (TuyaApiError, TuyaConnectionError) as err:
                _LOGGER.debug("Cannot read device %s: %s", device_id, err)

            if self._enable_shadow and device_id not in self._shadow_loaded:
                try:
                    device.shadow = await self.client.async_get_thing_shadow(device_id)
                    self._shadow_loaded.add(device_id)
                    self.iot_core_not_authorized = False
                except TuyaAuthorizationError as err:
                    if err.code == ERR_API_NOT_AUTHORIZED:
                        self.iot_core_not_authorized = True
                    _LOGGER.debug(
                        "No IoT Core permission for device %s: %s", device_id, err
                    )
                except (TuyaApiError, TuyaConnectionError) as err:
                    _LOGGER.debug(
                        "Cannot read shadow for device %s: %s", device_id, err
                    )
            devices[device_id] = device

        self._known = devices
        if self.config_entry.entry_id:
            from .repairs import async_update_issues

            async_update_issues(
                self.hass,
                self.config_entry.entry_id,
                api_not_authorized=self.api_not_authorized,
                iot_core_not_authorized=self.iot_core_not_authorized,
                device_count=len(devices),
            )
        return devices

    async def async_send_command(
        self, device_id: str, code: str, value: object
    ) -> None:
        """Send a command and refresh data afterwards."""
        await self.client.async_send_command(device_id, code, value)
        await self.async_request_refresh()
