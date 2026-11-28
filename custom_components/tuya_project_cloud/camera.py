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

# Home Assistant's Tuya camera (and Xtend Tuya, which inherits from it) asks
# for a fresh RTSP allocation on every stream start. A live probe on 2026-11-28
# decoded 884 frames in 60 s that way for the pan/tilt camera, while the
# battery-powered door viewer stayed asleep on RTSP (one packet in 30 s) and
# delivered 911 frames in 61 s over HLS. Select the stream type from the
# low-power DPS codes instead of guessing per device. A single
# `wireless_powermode`/`wireless_awake` code can also occur on mains-powered
# cameras, so require both unless `wireless_lowpower` is explicitly true.
STREAM_TYPE_PRIMARY = "rtsp"
STREAM_TYPE_FALLBACK = "hls"
LOW_POWER_DPS_CODE = "wireless_lowpower"
LOW_POWER_PAIR_CODES = frozenset({"wireless_awake", "wireless_powermode"})

# Signed URLs are short-lived. HA retries a failed stream with the same source
# until it works, so an expired URL has to be replaced explicitly.
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
    """Camera backed by a fresh short-lived Tuya allocation per stream start."""

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

    @staticmethod
    def _prefers_hls(device: TuyaDevice) -> bool:
        """Return whether a battery-powered camera needs the HLS path."""
        codes = set(device.status) | set(device.functions)
        if LOW_POWER_DPS_CODE in codes:
            # An explicit false value wins even if the pair codes are present.
            return device.status.get(LOW_POWER_DPS_CODE) is not False
        return LOW_POWER_PAIR_CODES <= codes

    async def _async_allocate_source(self) -> str | None:
        """Return a fresh source for the device's stream type."""
        device = self._tuya_device
        if not device or not device.online or not device.last_update_success:
            return None
        preferred = (
            STREAM_TYPE_FALLBACK if self._prefers_hls(device) else STREAM_TYPE_PRIMARY
        )
        alternate = (
            STREAM_TYPE_PRIMARY
            if preferred == STREAM_TYPE_FALLBACK
            else STREAM_TYPE_FALLBACK
        )
        for stream_type in (preferred, alternate):
            try:
                return await self.coordinator.client.async_allocate_stream(
                    self._device_id, stream_type
                )
            except TuyaApiError:
                _LOGGER.debug(
                    "Cannot allocate a stream for camera %s (%s)",
                    redact_identifier(self._device_id),
                    type(self).__name__,
                )
        if self._proxy_token and self._proxy is not None:
            self._proxy.invalidate(self._proxy_token)
            return self._proxy.source_url(self._proxy_token)
        return None

    async def _async_renew_stream_source(self) -> None:
        """Replace an expired source without exposing it anywhere."""
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
            source = await self._async_allocate_source()
            if source is None:
                return
            if self.stream is not stream:
                return
            stream.update_source(source)
            self._last_renewal = time.monotonic()

    async def stream_source(self) -> str | None:
        """Return a fresh source; signed URLs never reach HA state or logs."""
        device = self._tuya_device
        if not device or not device.online or not device.last_update_success:
            return None
        if self.stream is not None and not self.stream.available:
            self.stream = None
        return await self._async_allocate_source()

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return a still image from the same fresh source HA Core uses."""
        from homeassistant.components import ffmpeg

        # Allocate directly: a snapshot must not detach a live stream worker.
        source = await self._async_allocate_source()
        if not source:
            return None
        return await ffmpeg.async_get_image(
            self.hass, source, width=width, height=height
        )
