"""Camera platform for Tuya Project Cloud live streams."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.components.stream import Stream
from homeassistant.const import MATCH_ALL
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import TuyaApiError, TuyaDevice
from .const import CONF_ENABLE_CAMERA, DEFAULT_ENABLE_CAMERA
from .entity import tuya_device_info
from .stream_proxy import TuyaStreamProxy, async_register_stream_proxy
from .utils import redact_identifier

if TYPE_CHECKING:
    from .coordinator import (
        TuyaProjectCloudConfigEntry,
        TuyaProjectCloudCoordinator,
    )

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0

# Signed HLS URLs are short-lived. HA retries a failed stream with the same
# source until it works, so an expired URL has to be replaced explicitly.
MIN_SOURCE_RENEWAL_INTERVAL = 10.0

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
    proxy = async_register_stream_proxy(hass)
    entities = []
    for device in (coordinator.data or {}).values():
        if device.category not in CAMERA_CATEGORIES and not any(
            "stream" in code for code in device.functions
        ):
            continue
        token = proxy.register(device.id, coordinator)
        entities.append(TuyaCamera(coordinator, device, token, proxy))
    async_add_entities(entities)


class TuyaCamera(CoordinatorEntity["TuyaProjectCloudCoordinator"], Camera):
    """HLS camera backed by a short-lived Tuya stream allocation."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_supported_features = CameraEntityFeature.STREAM
    _unrecorded_attributes = frozenset(MATCH_ALL)

    def __init__(
        self,
        coordinator: TuyaProjectCloudCoordinator,
        device: TuyaDevice,
        proxy_token: str | None = None,
        proxy: TuyaStreamProxy | None = None,
    ) -> None:
        """Initialize the camera entity."""
        super().__init__(coordinator)
        # CoordinatorEntity does not chain to Camera.__init__ in all HA versions.
        Camera.__init__(self)
        self._device_id = device.id
        self._attr_unique_id = f"{device.id}_live"
        self._attr_device_info = tuya_device_info(device)
        self._proxy_token = proxy_token
        self._proxy = proxy
        self._renewal_lock: asyncio.Lock | None = None
        self._last_renewal: float | None = None

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

    async def async_create_stream(self) -> Stream | None:
        """Create a stream and observe its availability for URL renewal."""
        stream = await super().async_create_stream()
        if stream is not None:
            # HA uses this callback for state updates; keep that behaviour and
            # add our own reaction when the worker reports an unusable source.
            # Re-hook on every call, because HA may restore its own callback.
            stream.set_update_callback(self._async_stream_state_changed)
        return stream

    @callback
    def _async_stream_state_changed(self) -> None:
        """Write state and renew a stream whose source has become unusable."""
        self.async_write_ha_state()
        if self.stream is not None and not self.stream.available:
            self.hass.async_create_task(self._async_renew_stream_source())

    async def _async_renew_stream_source(self) -> None:
        """Replace an expired signed HLS URL without exposing it anywhere."""
        stream = self.stream
        if stream is None or stream.available:
            return
        if self._renewal_lock is None:
            self._renewal_lock = asyncio.Lock()
        async with self._renewal_lock:
            stream = self.stream
            if stream is None or stream.available:
                return
            now = time.monotonic()
            if (
                self._last_renewal is not None
                and now - self._last_renewal < MIN_SOURCE_RENEWAL_INTERVAL
            ):
                return
            device = self._tuya_device
            if not device or not device.online or not device.last_update_success:
                return
            if self._proxy_token and self._proxy is not None:
                self._proxy.invalidate(self._proxy_token)
                source = self._proxy.source_url(self._proxy_token)
            else:
                try:
                    source = await self.coordinator.client.async_allocate_stream(
                        self._device_id, "hls"
                    )
                except TuyaApiError:
                    _LOGGER.debug(
                        "Cannot renew a stream for camera %s (%s)",
                        redact_identifier(self._device_id),
                        type(self).__name__,
                    )
                    return
            if self.stream is not stream:
                return
            stream.update_source(source)
            self._last_renewal = time.monotonic()

    async def stream_source(self) -> str | None:
        """Return a stable local proxy URL; never expose signed URLs."""
        device = self._tuya_device
        if not device or not device.online or not device.last_update_success:
            return None
        if self.stream is not None and not self.stream.available:
            self.stream = None
        if self._proxy_token and self._proxy is not None:
            return self._proxy.source_url(self._proxy_token)
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
