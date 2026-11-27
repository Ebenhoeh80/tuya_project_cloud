"""Sensor platform for Tuya Project Cloud."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import TuyaFunction
from .dps import SENSOR_DESCRIPTIONS
from .entity import TuyaProjectCloudEntity, TuyaShadowEntity
from .interpret import (
    DpsSensorInterpretation,
    interpretation_for,
    interpreted_value,
)
from .shadow import CHARGER_SHADOW_SENSORS, has_shadow_sensors

PARALLEL_UPDATES = 0

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
            definition = device.specifications.get(code)
            if code not in SENSOR_DESCRIPTIONS and not any(
                hint in code.lower() for hint in SENSOR_HINTS
            ):
                continue
            description = SENSOR_DESCRIPTIONS.get(code) or SensorEntityDescription(
                key=code,
                translation_key="dps_unknown_sensor",
                translation_placeholders={"code": code},
                entity_category=EntityCategory.DIAGNOSTIC,
            )
            interpretation = interpretation_for(code, definition)
            if interpretation is not None:
                description = replace(
                    description,
                    translation_key=interpretation.translation_key,
                    device_class=interpretation.device_class,
                    native_unit_of_measurement=interpretation.native_unit,
                    suggested_unit_of_measurement=interpretation.suggested_unit,
                    state_class=interpretation.state_class,
                    suggested_display_precision=interpretation.precision,
                )
            entities.append(
                TuyaSensor(
                    coordinator,
                    device,
                    description,
                    code,
                    definition=definition,
                    interpretation=interpretation,
                )
            )
    known_shadow_ids: set[str] = set()

    def _new_shadow_sensors() -> list[TuyaShadowSensor]:
        """Collect shadow sensors that do not exist yet."""
        new: list[TuyaShadowSensor] = []
        for device in (coordinator.data or {}).values():
            if not has_shadow_sensors(device):
                continue
            for description in CHARGER_SHADOW_SENSORS:
                if description.code not in device.shadow:
                    continue
                unique_id = f"{device.id}_shadow_{description.key}"
                if unique_id in known_shadow_ids:
                    continue
                known_shadow_ids.add(unique_id)
                new.append(TuyaShadowSensor(coordinator, device, description))
        return new

    entities.extend(_new_shadow_sensors())

    @callback
    def _async_add_new_shadow_sensors() -> None:
        """Add sensors when a charger comes online after HA started."""
        if new := _new_shadow_sensors():
            async_add_entities(new)

    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_shadow_sensors))
    async_add_entities(entities)


class TuyaSensor(TuyaProjectCloudEntity, SensorEntity):
    """A sensor backed by a read-only DPS code."""

    def __init__(
        self,
        coordinator: Any,
        device: Any,
        description: SensorEntityDescription,
        dps_code: str,
        *,
        definition: TuyaFunction | None = None,
        interpretation: DpsSensorInterpretation | None = None,
    ) -> None:
        """Initialize a DPS sensor with its setup-time interpretation."""
        super().__init__(coordinator, device, description, dps_code)
        self._definition = definition
        self._interpretation = interpretation

    @property
    def native_value(self) -> Any:
        """Return the value using the interpretation chosen at setup."""
        return interpreted_value(self.dps_value, self._definition, self._interpretation)


class TuyaShadowSensor(TuyaShadowEntity, SensorEntity):
    """A sensor backed by an IoT Core thing shadow property."""

    @property
    def native_value(self) -> Any:
        """Return the scaled shadow value."""
        return self.shadow_sensor_value
