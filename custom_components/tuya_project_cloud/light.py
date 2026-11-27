"""Light platform for Tuya Project Cloud."""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ColorMode,
    LightEntity,
    LightEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import LIGHT_CODES
from .entity import TuyaProjectCloudEntity
from .utils import coerce_float


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Any,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up lights from DPS codes."""
    coordinator = entry.runtime_data
    entities: list[TuyaLight] = []
    for device in (coordinator.data or {}).values():
        codes = set(device.functions) | set(device.status)
        if not any(code in codes for code in LIGHT_CODES):
            continue
        switch_code = next((code for code in LIGHT_CODES if code in codes), None)
        brightness_code = next(
            (code for code in ("bright_value", "bright_value_v2") if code in codes),
            None,
        )
        color_mode = ColorMode.BRIGHTNESS if brightness_code else ColorMode.ONOFF
        entities.append(
            TuyaLight(
                coordinator,
                device,
                # Main entity: HA prepends the device name automatically.
                LightEntityDescription(key=switch_code),
                switch_code,
                brightness_code,
                color_mode,
            )
        )
    async_add_entities(entities)


class TuyaLight(TuyaProjectCloudEntity, LightEntity):
    """A light backed by switch and brightness DPS codes."""

    def __init__(
        self, coordinator, device, description, switch_code, brightness_code, color_mode
    ):
        """Initialize the light."""
        super().__init__(coordinator, device, description, switch_code)
        self._brightness_code = brightness_code
        self._attr_supported_color_modes = {color_mode}
        self._attr_color_mode = color_mode

    @property
    def is_on(self) -> bool:
        """Return the current state."""
        return bool(self.dps_value)

    @property
    def brightness(self) -> int | None:
        """Return brightness as 0-255."""
        if not self._brightness_code or not self._tuya_device:
            return None
        value = coerce_float(self._tuya_device.status.get(self._brightness_code))
        return round(value / 100 * 255) if value is not None else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the light on, optionally setting brightness."""
        if ATTR_BRIGHTNESS in kwargs and self._brightness_code:
            value = round(kwargs[ATTR_BRIGHTNESS] / 255 * 100)
            await self.coordinator.async_send_command(
                self._device_id, self._brightness_code, value
            )
        else:
            await self._async_send(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the light off."""
        await self._async_send(False)
