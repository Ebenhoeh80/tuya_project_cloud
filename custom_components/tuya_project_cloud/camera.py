"""Camera platform for Tuya Project Cloud live streams."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.const import MATCH_ALL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import TuyaApiError, TuyaDevice
from .const import CONF_ENABLE_CAMERA, DEFAULT_ENABLE_CAMERA
from .entity import tuya_device_info
from .utils import redact_identifier

if TYPE_CHECKING:
    from .coordinator import (
        TuyaProjectCloudConfigEntry,
        TuyaProjectCloudCoordinator,
    )

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0

# "sp" is the Tuya category for IP cameras; the door viewer was verified live.
CAMERA_CATEGORIES = frozenset({"sp"})


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TuyaProjectCloudConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up cameras for devices that expose a live stream."""
    if not entry.options.get(CONF_ENABLE_CAMERA, DEFAULT_ENABLE_CAMERA):
        return
    coordinator = entry.runtime_data
    entities = [
        TuyaCamera(coordinator, device)
        for device in (coordinator.data or {}).values()
        if device.category in CAMERA_CATEGORIES
        or any("stream" in code for code in device.functions)
    ]
    async_add_entities(entities)


class TuyaCamera(CoordinatorEntity["TuyaProjectCloudCoordinator"], Camera):
    """HLS camera backed by a short-lived Tuya stream allocation."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_supported_features = CameraEntityFeature.STREAM
    _unrecorded_attributes = frozenset(MATCH_ALL)

    def __init__(
        self, coordinator: TuyaProjectCloudCoordinator, device: TuyaDevice
    ) -> None:
        """Initialize the camera entity."""
        super().__init__(coordinator)
        # CoordinatorEntity does not chain to Camera.__init__ in all HA versions.
        Camera.__init__(self)
        self._device_id = device.id
        self._attr_unique_id = f"{device.id}_live"
        self._attr_device_info = tuya_device_info(device)

    @property
    def _tuya_device(self) -> TuyaDevice | None:
        """Return the current device data."""
        return (
            self.coordinator.data.get(self._device_id)
            if self.coordinator.data
            else None
        )

    @property
    def available(self) -> bool:
        """Match the other platforms: online and successfully refreshed."""
        device = self._tuya_device
        return super().available and bool(
            device and device.online and device.last_update_success
        )

    @property
    def is_streaming(self) -> bool:
        """Report whether a stream worker is currently attached."""
        return bool(self.stream and self.stream.available)

    async def stream_source(self) -> str | None:
        """Allocate a fresh signed URL; never expose or log it as an attribute."""
        device = self._tuya_device
        if not device or not device.online or not device.last_update_success:
            return None
        if self.stream is not None and not self.stream.available:
            self.stream = None
        try:
            return await self.coordinator.client.async_allocate_stream(
                self._device_id, "hls"
            )
        except TuyaApiError:
            _LOGGER.debug(
                "Cannot allocate a stream for camera %s (%s)",
                redact_identifier(self._device_id),
                type(self).__name__,
            )
            return None
