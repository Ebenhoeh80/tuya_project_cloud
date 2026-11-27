"""Tests for the camera platform."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.components.camera import CameraEntityFeature

from custom_components.tuya_project_cloud.api import TuyaApiError, TuyaDevice
from custom_components.tuya_project_cloud.camera import (
    async_setup_entry as camera_setup,
)


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
    coordinator.client.async_allocate_stream = AsyncMock(
        return_value="https://example.invalid/live.m3u8"
    )
    entry = MagicMock()
    entry.runtime_data = coordinator
    entry.options = {"enable_camera": enabled}
    return entry


@pytest.mark.asyncio
async def test_camera_uses_fresh_hls_url() -> None:
    """The camera requests a fresh signed URL and never stores it."""
    added: list = []
    entry = _entry()
    await camera_setup(MagicMock(), entry, lambda entities: added.extend(entities))
    assert len(added) == 1
    camera = added[0]
    assert CameraEntityFeature.STREAM in camera.supported_features
    assert await camera.stream_source() == "https://example.invalid/live.m3u8"
    entry.runtime_data.client.async_allocate_stream.assert_awaited_once_with(
        "cam1", "hls"
    )
    assert "https://example.invalid/live.m3u8" not in str(camera.state_attributes)
    assert "https://example.invalid/live.m3u8" not in str(camera.extra_state_attributes)


@pytest.mark.asyncio
async def test_camera_offline_has_no_source() -> None:
    """An offline camera does not allocate a stream."""
    added: list = []
    entry = _entry(online=False)
    await camera_setup(MagicMock(), entry, lambda entities: added.extend(entities))
    assert await added[0].stream_source() is None
    entry.runtime_data.client.async_allocate_stream.assert_not_awaited()


@pytest.mark.asyncio
async def test_stale_camera_is_unavailable_and_has_no_source() -> None:
    """A failed refresh marks the camera unavailable like every other entity."""
    added: list = []
    entry = _entry(refreshed=False)
    await camera_setup(MagicMock(), entry, lambda entities: added.extend(entities))
    camera = added[0]
    assert camera.available is False
    assert await camera.stream_source() is None
    entry.runtime_data.client.async_allocate_stream.assert_not_awaited()


@pytest.mark.asyncio
async def test_camera_option_disables_platform() -> None:
    """Disabling the option skips camera creation entirely."""
    added: list = []
    await camera_setup(
        MagicMock(), _entry(enabled=False), lambda entities: added.extend(entities)
    )
    assert added == []


@pytest.mark.asyncio
async def test_camera_stream_error_is_not_fatal() -> None:
    """An allocation error returns no source without breaking setup."""
    added: list = []
    entry = _entry()
    entry.runtime_data.client.async_allocate_stream = AsyncMock(
        side_effect=TuyaApiError("denied")
    )
    await camera_setup(MagicMock(), entry, lambda entities: added.extend(entities))
    assert await added[0].stream_source() is None


def _stream(*, available: bool = False) -> MagicMock:
    """Return a fake HA stream for renewal tests."""
    stream = MagicMock()
    stream.available = available
    return stream


async def _camera_with_stream(entry: MagicMock, stream: MagicMock) -> MagicMock:
    """Set up one camera and attach a fake stream to it."""
    added: list = []
    await camera_setup(MagicMock(), entry, lambda entities: added.extend(entities))
    camera = added[0]
    camera.stream = stream
    return camera


@pytest.mark.asyncio
async def test_expired_stream_source_is_renewed() -> None:
    """A failed worker gets a fresh signed URL instead of retrying a stale one."""
    entry = _entry()
    stream = _stream()
    camera = await _camera_with_stream(entry, stream)
    await camera._async_renew_stream_source()
    entry.runtime_data.client.async_allocate_stream.assert_awaited_once_with(
        "cam1", "hls"
    )
    stream.update_source.assert_called_once_with("https://example.invalid/live.m3u8")


@pytest.mark.asyncio
async def test_available_stream_is_not_renewed() -> None:
    """A healthy stream keeps its source and does not allocate again."""
    entry = _entry()
    stream = _stream(available=True)
    camera = await _camera_with_stream(entry, stream)
    await camera._async_renew_stream_source()
    entry.runtime_data.client.async_allocate_stream.assert_not_awaited()
    stream.update_source.assert_not_called()


@pytest.mark.asyncio
async def test_renewal_is_throttled_and_recovers_after_interval() -> None:
    """Repeated failures do not hammer Tuya, but still renew later."""
    entry = _entry()
    stream = _stream()
    camera = await _camera_with_stream(entry, stream)
    clock = {"now": 0.0}
    with patch(
        "custom_components.tuya_project_cloud.camera.time.monotonic",
        side_effect=lambda: clock["now"],
    ):
        await camera._async_renew_stream_source()
        await camera._async_renew_stream_source()
        clock["now"] = 100.0
        await camera._async_renew_stream_source()
    assert entry.runtime_data.client.async_allocate_stream.await_count == 2
    assert stream.update_source.call_count == 2


@pytest.mark.asyncio
async def test_renewal_allocation_error_is_not_fatal() -> None:
    """A failed renewal leaves the stream untouched and raises nothing."""
    entry = _entry()
    entry.runtime_data.client.async_allocate_stream = AsyncMock(
        side_effect=TuyaApiError("denied")
    )
    stream = _stream()
    camera = await _camera_with_stream(entry, stream)
    await camera._async_renew_stream_source()
    stream.update_source.assert_not_called()


@pytest.mark.asyncio
async def test_offline_camera_does_not_renew() -> None:
    """An offline or stale device never triggers a new stream allocation."""
    entry = _entry(online=False)
    stream = _stream()
    camera = await _camera_with_stream(entry, stream)
    await camera._async_renew_stream_source()
    entry.runtime_data.client.async_allocate_stream.assert_not_awaited()
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
    with patch(
        "homeassistant.components.camera.Camera.async_create_stream",
        new_callable=AsyncMock,
        return_value=stream,
    ) as create_stream:
        assert await camera.async_create_stream() is stream
    create_stream.assert_awaited_once()
    stream.set_update_callback.assert_called_once()
    callback = stream.set_update_callback.call_args.args[0]
    callback()
    camera.async_write_ha_state.assert_called_once()
    assert len(tasks) == 1
    await tasks[0]
    entry.runtime_data.client.async_allocate_stream.assert_awaited_once_with(
        "cam1", "hls"
    )
    stream.update_source.assert_called_once_with("https://example.invalid/live.m3u8")


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
        # Older HA versions restore their own callback on each call.
        stream.set_update_callback(MagicMock())
        return stream

    with patch(
        "homeassistant.components.camera.Camera.async_create_stream",
        new=create_stream,
    ):
        await camera.async_create_stream()
        await camera.async_create_stream()
    # The mocked base re-hooks once per call, our override re-hooks once too.
    assert stream.set_update_callback.call_count == 4
    callback = stream.set_update_callback.call_args.args[0]
    callback()
    assert len(tasks) == 1
    await tasks[0]
    stream.update_source.assert_called_once_with("https://example.invalid/live.m3u8")


@pytest.mark.asyncio
async def test_renewal_applies_fresh_url_if_worker_recovers_during_allocation() -> None:
    """A recovered worker must not cause an already allocated URL to be dropped."""
    entry = _entry()
    stream = _stream()
    camera = await _camera_with_stream(entry, stream)

    async def allocate(*args: object, **kwargs: object) -> str:
        stream.available = True
        return "https://example.invalid/live.m3u8"

    entry.runtime_data.client.async_allocate_stream = AsyncMock(side_effect=allocate)
    await camera._async_renew_stream_source()
    stream.update_source.assert_called_once_with("https://example.invalid/live.m3u8")


@pytest.mark.asyncio
async def test_renewal_does_not_touch_a_replaced_stream() -> None:
    """A URL allocated for a detached stream is not applied to the new one."""
    entry = _entry()
    stream = _stream()
    camera = await _camera_with_stream(entry, stream)

    async def allocate(*args: object, **kwargs: object) -> str:
        camera.stream = _stream()
        return "https://example.invalid/live.m3u8"

    entry.runtime_data.client.async_allocate_stream = AsyncMock(side_effect=allocate)
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
    stream = _stream()
    camera = await _camera_with_stream(entry, stream)
    with caplog.at_level(
        logging.DEBUG, logger="custom_components.tuya_project_cloud.camera"
    ):
        await camera._async_renew_stream_source()
    assert "cam1" not in caplog.text
    assert "https://example.invalid" not in caplog.text
