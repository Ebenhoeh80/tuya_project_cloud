"""Sensor platform for Tuya Project Cloud."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import TuyaProjectCloudEntity, TuyaShadowEntity
from .shadow import CHARGER_SHADOW_SENSORS, has_shadow_sensors

SENSOR_HINTS = (
    "battery",
    "temperature",
    "humidity",
    "power",
    "energy",
    "pm25",
    "pm10",
    "co2",
    "signal",
    "status",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Any,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors from read-only DPS codes."""
    coordinator = entry.runtime_data
    entities: list[TuyaSensor] = []
    for device in (coordinator.data or {}).values():
        for code in device.status:
            if code in device.functions:
                continue
            if not any(hint in code.lower() for hint in SENSOR_HINTS):
                continue
            entities.append(
                TuyaSensor(
                    coordinator,
                    device,
                    SensorEntityDescription(
                        key=code,
                        name=code.replace("_", " ").title(),
                        entity_category=EntityCategory.DIAGNOSTIC,
                    ),
                    code,
                )
            )
    for device in (coordinator.data or {}).values():
        if not has_shadow_sensors(device):
            continue
        for description in CHARGER_SHADOW_SENSORS:
            if description.code in device.shadow:
                entities.append(TuyaShadowSensor(coordinator, device, description))
    async_add_entities(entities)


class TuyaSensor(TuyaProjectCloudEntity, SensorEntity):
    """A sensor backed by a read-only DPS code."""

    @property
    def native_value(self) -> Any:
        """Return the current sensor value."""
        return self.dps_value


class TuyaShadowSensor(TuyaShadowEntity, SensorEntity):
    """A sensor backed by an IoT Core thing shadow property."""

    @property
    def native_value(self) -> Any:
        """Return the scaled shadow value."""
        return self.shadow_sensor_value
