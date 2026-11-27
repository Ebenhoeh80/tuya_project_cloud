"""DataUpdateCoordinator for Tuya Project Cloud."""

from __future__ import annotations

import logging
import time
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ServiceValidationError
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
    ERR_NO_PERMISSION,
    SHADOW_REFRESH_INTERVAL,
)
from .repairs import async_update_command_issue, async_update_issues
from .utils import redact_identifier

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
        self._enable_shadow = bool(
            entry.options.get(CONF_ENABLE_SHADOW, DEFAULT_ENABLE_SHADOW)
        )
        self._last_issue_state: tuple[bool, bool, int] | None = None
        self._last_shadow_refresh: dict[str, float] = {}

    async def _async_update_data(self) -> dict[str, TuyaDevice]:
        """Fetch devices, functions and status."""
        try:
            raw_devices = await self.client.async_get_devices()
        except TuyaAuthenticationError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except (TuyaApiError, TuyaConnectionError) as err:
            raise UpdateFailed(f"Cannot fetch devices: {err}") from err

        devices: dict[str, TuyaDevice] = {}
        api_denied = False
        iot_core_denied = False
        now = time.monotonic()
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
            label = redact_identifier(device_id)

            # Status determines freshness; static metadata is read only once.
            try:
                device.status = await self.client.async_get_status(device_id)
                device.last_update_success = True
            except TuyaAuthorizationError as err:
                device.last_update_success = False
                if err.code == ERR_API_NOT_AUTHORIZED:
                    api_denied = True
                _LOGGER.debug("No API permission for device %s: %s", label, err)
            except (TuyaApiError, TuyaConnectionError) as err:
                device.last_update_success = False
                _LOGGER.debug("Cannot read device %s: %s", label, err)

            if not device.functions:
                try:
                    device.functions = await self.client.async_get_functions(device_id)
                except TuyaAuthorizationError as err:
                    if err.code == ERR_API_NOT_AUTHORIZED:
                        api_denied = True
                    _LOGGER.debug("No function permission for %s: %s", label, err)
                except (TuyaApiError, TuyaConnectionError) as err:
                    _LOGGER.debug("Cannot read functions for %s: %s", label, err)
            if not device.specifications:
                try:
                    device.specifications = await self.client.async_get_specifications(
                        device_id
                    )
                except (TuyaApiError, TuyaConnectionError) as err:
                    _LOGGER.debug("Cannot read specifications for %s: %s", label, err)

            # Charger values change while charging. Refresh on a slower cadence
            # and retry quickly when the first response was empty or failed.
            last_refresh = self._last_shadow_refresh.get(device_id, 0.0)
            shadow_due = (
                not device.shadow or now - last_refresh >= SHADOW_REFRESH_INTERVAL
            )
            if self._enable_shadow and device.online and shadow_due:
                try:
                    device.shadow = await self.client.async_get_thing_shadow(device_id)
                    self._last_shadow_refresh[device_id] = now
                except TuyaAuthorizationError as err:
                    if err.code == ERR_API_NOT_AUTHORIZED:
                        iot_core_denied = True
                    _LOGGER.debug(
                        "No IoT Core permission for device %s: %s", label, err
                    )
                except (TuyaApiError, TuyaConnectionError) as err:
                    _LOGGER.debug("Cannot read shadow for device %s: %s", label, err)
            devices[device_id] = device

        self._known = devices
        self.api_not_authorized = api_denied
        self.iot_core_not_authorized = iot_core_denied

        issue_state = (api_denied, iot_core_denied, len(devices))
        if self.config_entry.entry_id and issue_state != self._last_issue_state:
            async_update_issues(
                self.hass,
                self.config_entry.entry_id,
                api_not_authorized=api_denied,
                iot_core_not_authorized=iot_core_denied,
                device_count=len(devices),
            )
            self._last_issue_state = issue_state
        return devices

    async def async_send_command(
        self, device_id: str, code: str, value: object
    ) -> None:
        """Send a command, surface Tuya's denial as a repair and refresh data."""
        try:
            await self.client.async_send_command(device_id, code, value)
        except TuyaAuthorizationError as err:
            if err.code == ERR_NO_PERMISSION:
                if self.config_entry.entry_id:
                    async_update_command_issue(
                        self.hass, self.config_entry.entry_id, not_authorized=True
                    )
                raise ServiceValidationError(
                    "Tuya rejected the device command",
                    translation_domain=DOMAIN,
                    translation_key="command_not_authorized",
                ) from err
            raise
        if self.config_entry.entry_id:
            async_update_command_issue(
                self.hass, self.config_entry.entry_id, not_authorized=False
            )
        await self.async_request_refresh()
