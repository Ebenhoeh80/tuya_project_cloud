"""Switch platform for Tuya Project Cloud."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import LIGHT_CODES
from .entity import TuyaProjectCloudEntity

SWITCH_HINTS = ("switch", "onoff", "power", "enable", "pir_switch", "doorbell_active")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Any,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up switches from writable boolean DPS codes."""
    coordinator = entry.runtime_data
    entities: list[TuyaSwitch] = []
    for device in (coordinator.data or {}).values():
        for code, function in device.functions.items():
            # Keep the established type/name heuristic for backwards
            # compatibility: live devices use Boolean, Enum, Integer and String
            # codes here. Only light codes are excluded to avoid a duplicate
            # control next to the light entity.
            if function.type != "Boolean" and not any(
                hint in code.lower() for hint in SWITCH_HINTS
            ):
                continue
            if code in LIGHT_CODES:
                continue
            entities.append(
                TuyaSwitch(
                    coordinator,
                    device,
                    SwitchEntityDescription(
                        key=code,
                        name=code.replace("_", " ").title(),
                    ),
                    code,
                )
            )
    async_add_entities(entities)


class TuyaSwitch(TuyaProjectCloudEntity, SwitchEntity):
    """A switch backed by a boolean DPS code."""

    @property
    def is_on(self) -> bool:
        """Return the current state."""
        return bool(self.dps_value)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        await self._async_send(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        await self._async_send(False)
