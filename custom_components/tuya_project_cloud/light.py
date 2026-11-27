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

from .entity import TuyaProjectCloudEntity

LIGHT_CODES = {"switch_led", "led_switch", "light", "switch_light"}


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
        if not codes & LIGHT_CODES:
            continue
        switch_code = next(iter(codes & LIGHT_CODES))
        brightness_code = next(
            (code for code in ("bright_value", "bright_value_v2") if code in codes),
            None,
        )
        color_mode = ColorMode.BRIGHTNESS if brightness_code else ColorMode.ONOFF
        entities.append(
            TuyaLight(
                coordinator,
                device,
                LightEntityDescription(key=switch_code, name=device.name),
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
        value = self._tuya_device.status.get(self._brightness_code)
        return round(float(value) / 100 * 255) if value is not None else None

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
