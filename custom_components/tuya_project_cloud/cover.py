"""Cover platform for Tuya Project Cloud."""

from __future__ import annotations

from typing import Any

from homeassistant.components.cover import (
    CoverDeviceClass,
    CoverEntity,
    CoverEntityDescription,
    CoverEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import TuyaProjectCloudEntity

COVER_CATEGORIES = {"cl", "curtain", "jc"}
CONTROL_CODES = {"control", "control_2", "switch"}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Any,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up covers from DPS codes."""
    coordinator = entry.runtime_data
    entities: list[TuyaCover] = []
    for device in (coordinator.data or {}).values():
        codes = set(device.functions) | set(device.status)
        control = next((code for code in CONTROL_CODES if code in codes), None)
        if not control and device.category not in COVER_CATEGORIES:
            continue
        position = next(
            (code for code in ("percent_control", "position") if code in codes),
            None,
        )
        entities.append(
            TuyaCover(
                coordinator,
                device,
                CoverEntityDescription(
                    key=control or "position",
                    name=device.name,
                    device_class=CoverDeviceClass.CURTAIN,
                ),
                control,
                position,
            )
        )
    async_add_entities(entities)


class TuyaCover(TuyaProjectCloudEntity, CoverEntity):
    """A cover backed by Tuya DPS codes."""

    def __init__(self, coordinator, device, description, control_code, position_code):
        """Initialize the cover."""
        super().__init__(
            coordinator,
            device,
            description,
            control_code or position_code or "position",
        )
        self._control_code = control_code
        self._position_code = position_code
        features = CoverEntityFeature(0)
        if control_code:
            features |= (
                CoverEntityFeature.OPEN
                | CoverEntityFeature.CLOSE
                | CoverEntityFeature.STOP
            )
        if position_code:
            features |= CoverEntityFeature.SET_POSITION
        self._attr_supported_features = features

    @property
    def is_closed(self) -> bool | None:
        """Return whether the cover is closed."""
        device = self._tuya_device
        if not device or not self._position_code:
            return None
        value = device.status.get(self._position_code)
        return int(value) == 0 if value is not None else None

    @property
    def current_cover_position(self) -> int | None:
        """Return the current position."""
        device = self._tuya_device
        if not device or not self._position_code:
            return None
        value = device.status.get(self._position_code)
        return int(value) if value is not None else None

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the cover."""
        if self._control_code:
            await self.coordinator.async_send_command(
                self._device_id, self._control_code, "open"
            )

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the cover."""
        if self._control_code:
            await self.coordinator.async_send_command(
                self._device_id, self._control_code, "close"
            )

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop the cover."""
        if self._control_code:
            await self.coordinator.async_send_command(
                self._device_id, self._control_code, "stop"
            )

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Set the cover position."""
        if self._position_code and (position := kwargs.get("position")) is not None:
            await self.coordinator.async_send_command(
                self._device_id, self._position_code, int(position)
            )
