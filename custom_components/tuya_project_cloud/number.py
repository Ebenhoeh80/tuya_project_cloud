"""Number platform for Tuya Project Cloud."""

from __future__ import annotations

import dataclasses
from typing import Any

from homeassistant.components.number import NumberEntity, NumberEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import LIGHT_CODES
from .dps import NUMBER_DESCRIPTIONS
from .entity import TuyaProjectCloudEntity
from .utils import coerce_float

PARALLEL_UPDATES = 1

# "bright_value" was already reserved for the light platform in v0.2.4. The v2
# variant is only skipped when the light actually uses it; otherwise the number
# entity from v0.2.4 must remain available.
EXCLUDED_CODES = {
    "bright_value",
    "temp_value",
    "temp_set",
    "percent_control",
    "position",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Any,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up numbers from integer DPS codes with a range."""
    coordinator = entry.runtime_data
    entities: list[TuyaNumber] = []
    for device in (coordinator.data or {}).values():
        codes = set(device.functions) | set(device.status)
        has_light = any(code in LIGHT_CODES for code in codes)
        for code, function in device.functions.items():
            if code in EXCLUDED_CODES:
                continue
            if code == "bright_value_v2" and has_light and "bright_value" not in codes:
                continue
            if function.type != "Integer":
                continue
            values = function.values
            if not isinstance(values, dict):
                continue
            try:
                minimum = float(values["min"])
                maximum = float(values["max"])
                step = float(values.get("step", 1))
            except (KeyError, TypeError, ValueError):
                continue
            if minimum >= maximum or step <= 0:
                continue
            description = NUMBER_DESCRIPTIONS.get(code) or NumberEntityDescription(
                key=code,
                translation_key="dps_unknown_number",
                translation_placeholders={"code": code},
            )
            description = dataclasses.replace(
                description,
                native_min_value=minimum,
                native_max_value=maximum,
                native_step=step,
            )
            entities.append(TuyaNumber(coordinator, device, description, code))
    async_add_entities(entities)


class TuyaNumber(TuyaProjectCloudEntity, NumberEntity):
    """A number backed by an integer DPS code."""

    @property
    def native_value(self) -> float | None:
        """Return the current value, tolerating unexpected Tuya payloads."""
        return coerce_float(self.dps_value)

    async def async_set_native_value(self, value: float) -> None:
        """Set the value."""
        await self._async_send(int(value))
