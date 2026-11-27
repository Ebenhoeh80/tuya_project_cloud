"""Climate platform for Tuya Project Cloud."""

from __future__ import annotations

from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityDescription,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import TuyaProjectCloudEntity
from .utils import coerce_float

PARALLEL_UPDATES = 1

CLIMATE_CATEGORIES = {"kt", "ykq", "hvac"}
MODE_VALUES = {
    "auto": HVACMode.AUTO,
    "cool": HVACMode.COOL,
    "heat": HVACMode.HEAT,
    "dry": HVACMode.DRY,
    "fan": HVACMode.FAN_ONLY,
    "off": HVACMode.OFF,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Any,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up climate entities from DPS codes."""
    coordinator = entry.runtime_data
    entities: list[TuyaClimate] = []
    for device in (coordinator.data or {}).values():
        codes = set(device.functions) | set(device.status)
        if device.category not in CLIMATE_CATEGORIES and "temp_set" not in codes:
            continue
        entities.append(
            TuyaClimate(
                coordinator,
                device,
                # Main entity: HA prepends the device name automatically.
                ClimateEntityDescription(key="temp_set"),
                codes,
            )
        )
    async_add_entities(entities)


class TuyaClimate(TuyaProjectCloudEntity, ClimateEntity):
    """A climate entity backed by Tuya DPS codes."""

    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS

    def __init__(self, coordinator, device, description, codes):
        """Initialize the climate entity."""
        super().__init__(coordinator, device, description, "temp_set")
        self._codes = codes
        self._attr_hvac_modes = list(MODE_VALUES.values())
        features = ClimateEntityFeature(0)
        if "temp_set" in device.functions:
            features |= ClimateEntityFeature.TARGET_TEMPERATURE
        self._attr_supported_features = features

    @property
    def native_current_temperature(self) -> float | None:
        """Return the current temperature."""
        device = self._tuya_device
        if not device:
            return None
        for code in ("temp_current", "temperature", "temp_show"):
            if code in device.status:
                return coerce_float(device.status[code])
        return None

    @property
    def native_target_temperature(self) -> float | None:
        """Return the target temperature, tolerating unexpected payloads."""
        return coerce_float(self.dps_value)

    @property
    def hvac_mode(self) -> HVACMode:
        """Return the current HVAC mode."""
        device = self._tuya_device
        if not device or not device.status.get("power", True):
            return HVACMode.OFF
        value = str(device.status.get("mode", "auto")).lower()
        return MODE_VALUES.get(value, HVACMode.AUTO)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set the target temperature."""
        if (temperature := kwargs.get("temperature")) is not None:
            await self._async_send(int(temperature))

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set the HVAC mode."""
        if "power" in self._codes:
            await self.coordinator.async_send_command(
                self._device_id, "power", hvac_mode != HVACMode.OFF
            )
        reverse = {value: key for key, value in MODE_VALUES.items()}
        if "mode" in self._codes and hvac_mode in reverse:
            await self.coordinator.async_send_command(
                self._device_id, "mode", reverse[hvac_mode]
            )
