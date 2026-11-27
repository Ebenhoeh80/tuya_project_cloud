"""Number platform for Tuya Project Cloud."""

from __future__ import annotations

from typing import Any

from homeassistant.components.number import NumberEntity, NumberEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import TuyaProjectCloudEntity

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
        for code, function in device.functions.items():
            if code in EXCLUDED_CODES:
                continue
            if function.type != "Integer":
                continue
            values = function.values or {}
            if "min" not in values or "max" not in values:
                continue
            entities.append(
                TuyaNumber(
                    coordinator,
                    device,
                    NumberEntityDescription(
                        key=code,
                        name=code.replace("_", " ").title(),
                        native_min_value=float(values["min"]),
                        native_max_value=float(values["max"]),
                        native_step=float(values.get("step", 1)),
                    ),
                    code,
                )
            )
    async_add_entities(entities)


class TuyaNumber(TuyaProjectCloudEntity, NumberEntity):
    """A number backed by an integer DPS code."""

    @property
    def native_value(self) -> float | None:
        """Return the current value."""
        value = self.dps_value
        return float(value) if value is not None else None

    async def async_set_native_value(self, value: float) -> None:
        """Set the value."""
        await self._async_send(int(value))
