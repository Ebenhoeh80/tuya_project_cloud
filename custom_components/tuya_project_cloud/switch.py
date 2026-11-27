"""Switch platform for Tuya Project Cloud."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import TuyaProjectCloudEntity

_LOGGER = logging.getLogger(__name__)

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
            if function.type != "Boolean" and not any(
                hint in code.lower() for hint in SWITCH_HINTS
            ):
                continue
            entities.append(
                TuyaSwitch(
                    coordinator,
                    device,
                    SwitchEntityDescription(
                        key=code,
                        translation_key="tuya_switch",
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
