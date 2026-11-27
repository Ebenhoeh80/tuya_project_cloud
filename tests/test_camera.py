"""Tests for the camera platform."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.components.camera import CameraEntityFeature

from custom_components.tuya_project_cloud.api import TuyaApiError, TuyaDevice
from custom_components.tuya_project_cloud.camera import (
    TuyaCamera,
)
from custom_components.tuya_project_cloud.camera import (
    async_setup_entry as camera_setup,
)
from custom_components.tuya_project_cloud.stream_proxy import PLAYLIST_PATH

DIRECT_URL = "https://example.invalid/live.m3u8"


def _entry(
    *, online: bool = True, enabled: bool = True, refreshed: bool = True
) -> MagicMock:
    """Return an entry with one mocked camera device."""
    device = TuyaDevice(
        id="cam1",
        name="Door viewer",
        category="sp",
        product_id="p1",
        online=online,
        last_update_success=refreshed,
    )
    coordinator = MagicMock()
    coordinator.data = {"cam1": device}
    coordinator.client.async_allocate_stream = AsyncMock(return_value=DIRECT_URL)
    entry = MagicMock()
    entry.runtime_data = coordinator
    entry.options = {"enable_camera": enabled}
    return entry


async def _setup_camera(entry: MagicMock) -> MagicMock:
    """Set up the platform and return the single camera entity."""
    hass = MagicMock()
    hass.data = {}
    added: list = []
    await camera_setup(hass, entry, lambda entities: added.extend(entities))
    assert len(added) == 1
    return added[0]


def _stream(*, available: bool = False) -> MagicMock:
    """Return a fake HA stream for renewal tests."""
    stream = MagicMock()
    stream.available = available
    return stream


async def _camera_with_stream(entry: MagicMock, stream: MagicMock) -> MagicMock:
    """Set up one camera and attach a fake stream to it."""
    camera = await _setup_camera(entry)
    camera.stream = stream
    return camera


@pytest.mark.asyncio
async def test_camera_uses_stable_local_proxy_url() -> None:
    """Entities expose a stable local URL, never the signed Tuya URL."""
    entry = _entry()
    camera = await _setup_camera(entry)
    assert CameraEntityFeature.STREAM in camera.supported_features
    source = await camera.stream_source()
    assert source is not None
    assert source.startswith("http")
    assert f"{PLAYLIST_PATH}/" in source
    assert source.endswith("/index.m3u8")
    entry.runtime_data.client.async_allocate_stream.assert_not_awaited()
    assert DIRECT_URL not in str(camera.state_attributes)
    assert DIRECT_URL not in str(camera.extra_state_attributes)
    assert "/index.m3u8" not in str(camera.state_attributes)


@pytest.mark.asyncio
async def test_camera_without_proxy_falls_back_to_direct_hls() -> None:
    """A camera constructed without a proxy keeps the previous behaviour."""
    entry = _entry()
    coordinator = entry.runtime_data
    camera = TuyaCamera(coordinator, coordinator.data["cam1"])
    assert await camera.stream_source() == DIRECT_URL
    entry.runtime_data.client.async_allocate_stream.assert_awaited_once_with(
        "cam1", "hls"
    )


@pytest.mark.asyncio
async def test_camera_offline_has_no_source() -> None:
    """An offline camera does not expose a stream."""
    entry = _entry(online=False)
    assert await (await _setup_camera(entry)).stream_source() is None
    entry.runtime_data.client.async_allocate_stream.assert_not_awaited()


@pytest.mark.asyncio
async def test_stale_camera_is_unavailable_and_has_no_source() -> None:
    """A failed refresh marks the camera unavailable like every other entity."""
    entry = _entry(refreshed=False)
    camera = await _setup_camera(entry)
    assert camera.available is False
    assert await camera.stream_source() is None
    entry.runtime_data.client.async_allocate_stream.assert_not_awaited()


@pytest.mark.asyncio
async def test_camera_option_disables_platform() -> None:
    """Disabling the option skips camera creation entirely."""
    hass = MagicMock()
    hass.data = {}
    added: list = []
    await camera_setup(
        hass, _entry(enabled=False), lambda entities: added.extend(entities)
    )
    assert added == []


@pytest.mark.asyncio
async def test_fallback_allocation_error_is_not_fatal() -> None:
    """A direct allocation error returns no source without breaking setup."""
    entry = _entry()
    entry.runtime_data.client.async_allocate_stream = AsyncMock(
        side_effect=TuyaApiError("denied")
    )
    coordinator = entry.runtime_data
    camera = TuyaCamera(coordinator, coordinator.data["cam1"])
    assert await camera.stream_source() is None


@pytest.mark.asyncio
async def test_expired_stream_source_is_renewed() -> None:
    """A failed worker invalidates the proxy and restarts with the same URL."""
    entry = _entry()
    stream = _stream()
    camera = await _setup_camera(entry)
    source = await camera.stream_source()
    camera.stream = stream
    with patch.object(
        camera._proxy, "invalidate", wraps=camera._proxy.invalidate
    ) as invalidate:
        await camera._async_renew_stream_source()
    assert invalidate.call_count == 1
    stream.update_source.assert_called_once_with(source)
    entry.runtime_data.client.async_allocate_stream.assert_not_awaited()


@pytest.mark.asyncio
async def test_available_stream_is_not_renewed() -> None:
    """A healthy stream keeps its source and does not touch the proxy."""
    entry = _entry()
    stream = _stream(available=True)
    camera = await _camera_with_stream(entry, stream)
    with patch.object(
        camera._proxy, "invalidate", wraps=camera._proxy.invalidate
    ) as invalidate:
        await camera._async_renew_stream_source()
    invalidate.assert_not_called()
    stream.update_source.assert_not_called()


@pytest.mark.asyncio
async def test_renewal_is_throttled_and_recovers_after_interval() -> None:
    """Repeated failures do not hammer the proxy, but still renew later."""
    entry = _entry()
    stream = _stream()
    camera = await _camera_with_stream(entry, stream)
    clock = {"now": 0.0}
    with (
        patch(
            "custom_components.tuya_project_cloud.camera.time.monotonic",
            side_effect=lambda: clock["now"],
        ),
        patch.object(
            camera._proxy, "invalidate", wraps=camera._proxy.invalidate
        ) as invalidate,
    ):
        await camera._async_renew_stream_source()
        await camera._async_renew_stream_source()
        clock["now"] = 100.0
        await camera._async_renew_stream_source()
    assert invalidate.call_count == 2
    assert stream.update_source.call_count == 2


@pytest.mark.asyncio
async def test_fallback_renewal_allocation_error_is_not_fatal() -> None:
    """A failed direct renewal leaves the stream untouched and raises nothing."""
    entry = _entry()
    entry.runtime_data.client.async_allocate_stream = AsyncMock(
        side_effect=TuyaApiError("denied")
    )
    coordinator = entry.runtime_data
    camera = TuyaCamera(coordinator, coordinator.data["cam1"])
    stream = _stream()
    camera.stream = stream
    await camera._async_renew_stream_source()
    stream.update_source.assert_not_called()


@pytest.mark.asyncio
async def test_offline_camera_does_not_renew() -> None:
    """An offline or stale device never triggers a proxy renewal."""
    entry = _entry(online=False)
    stream = _stream()
    camera = await _camera_with_stream(entry, stream)
    with patch.object(
        camera._proxy, "invalidate", wraps=camera._proxy.invalidate
    ) as invalidate:
        await camera._async_renew_stream_source()
    invalidate.assert_not_called()
    stream.update_source.assert_not_called()


@pytest.mark.asyncio
async def test_stream_state_callback_triggers_renewal() -> None:
    """HA's state callback is retained and starts a renewal on failure."""
    entry = _entry()
    stream = _stream()
    camera = await _camera_with_stream(entry, stream)
    camera.hass = MagicMock()
    camera.async_write_ha_state = MagicMock()
    tasks: list = []
    camera.hass.async_create_task = lambda coro: tasks.append(coro)
    with (
        patch(
            "homeassistant.components.camera.Camera.async_create_stream",
            new_callable=AsyncMock,
            return_value=stream,
        ),
        patch.object(
            camera._proxy, "invalidate", wraps=camera._proxy.invalidate
        ) as invalidate,
    ):
        assert await camera.async_create_stream() is stream
        stream.set_update_callback.assert_called_once()
        callback = stream.set_update_callback.call_args.args[0]
        callback()
        camera.async_write_ha_state.assert_called_once()
        assert len(tasks) == 1
        await tasks[0]
    invalidate.assert_called_once()
    assert stream.update_source.call_args.args[0].endswith("/index.m3u8")


@pytest.mark.asyncio
async def test_callback_is_reinstalled_on_repeated_stream_creation() -> None:
    """A later HA callback overwrite cannot disable URL renewal."""
    entry = _entry()
    stream = _stream()
    camera = await _camera_with_stream(entry, stream)
    camera.hass = MagicMock()
    camera.async_write_ha_state = MagicMock()
    tasks: list = []
    camera.hass.async_create_task = lambda coro: tasks.append(coro)

    async def create_stream(*args: object, **kwargs: object) -> MagicMock:
        stream.set_update_callback(MagicMock())
        return stream

    with patch(
        "homeassistant.components.camera.Camera.async_create_stream",
        new=create_stream,
    ):
        await camera.async_create_stream()
        await camera.async_create_stream()
    assert stream.set_update_callback.call_count == 4
    callback = stream.set_update_callback.call_args.args[0]
    callback()
    assert len(tasks) == 1
    await tasks[0]
    assert stream.update_source.call_args.args[0].endswith("/index.m3u8")


@pytest.mark.asyncio
async def test_renewal_applies_source_if_worker_recovers_during_renewal() -> None:
    """A recovered worker must not cause the prepared source to be dropped."""
    entry = _entry()
    stream = _stream()
    camera = await _camera_with_stream(entry, stream)

    def invalidate(*args: object) -> None:
        stream.available = True

    with patch.object(camera._proxy, "invalidate", side_effect=invalidate):
        await camera._async_renew_stream_source()
    assert stream.update_source.call_count == 1


@pytest.mark.asyncio
async def test_renewal_does_not_touch_a_replaced_stream() -> None:
    """A source prepared for a detached stream is not applied to the new one."""
    entry = _entry()
    stream = _stream()
    camera = await _camera_with_stream(entry, stream)

    def invalidate(*args: object) -> None:
        camera.stream = _stream()

    with patch.object(camera._proxy, "invalidate", side_effect=invalidate):
        await camera._async_renew_stream_source()
    stream.update_source.assert_not_called()


@pytest.mark.asyncio
async def test_renewal_logs_no_url_or_device_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Even debug messages must not expose the signed URL or device identifier."""
    entry = _entry()
    entry.runtime_data.client.async_allocate_stream = AsyncMock(
        side_effect=TuyaApiError("denied")
    )
    coordinator = entry.runtime_data
    camera = TuyaCamera(coordinator, coordinator.data["cam1"])
    stream = _stream()
    camera.stream = stream
    with caplog.at_level(
        logging.DEBUG, logger="custom_components.tuya_project_cloud.camera"
    ):
        await camera._async_renew_stream_source()
    assert "cam1" not in caplog.text
    assert DIRECT_URL not in caplog.text
