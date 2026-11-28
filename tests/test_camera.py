"""Tests for the camera platform."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, call, patch

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

DIRECT_URL = "rtsp://example.invalid:554/live"
FALLBACK_URL = "https://example.invalid/live.m3u8"


def _entry(
    *,
    online: bool = True,
    enabled: bool = True,
    refreshed: bool = True,
    dps_codes: tuple[str, ...] = (),
) -> MagicMock:
    """Return an entry with one mocked camera device."""
    device = TuyaDevice(
        id="cam1",
        name="Door viewer",
        category="sp",
        product_id="p1",
        online=online,
        last_update_success=refreshed,
        status={code: True for code in dps_codes},
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
async def test_camera_uses_fresh_rtsp_url() -> None:
    """Every stream start gets a fresh RTSP URL; signed URLs stay out of state."""
    entry = _entry()
    camera = await _setup_camera(entry)
    assert CameraEntityFeature.STREAM in camera.supported_features
    source = await camera.stream_source()
    assert source == DIRECT_URL
    entry.runtime_data.client.async_allocate_stream.assert_awaited_once_with(
        "cam1", "rtsp"
    )
    assert DIRECT_URL not in str(camera.state_attributes)
    assert DIRECT_URL not in str(camera.extra_state_attributes)


@pytest.mark.asyncio
async def test_low_power_camera_uses_stable_hls_proxy() -> None:
    """Battery-powered cameras use the proven HLS proxy, not a direct URL."""
    entry = _entry(dps_codes=("wireless_lowpower",))
    camera = await _setup_camera(entry)
    with patch.object(camera._proxy, "invalidate") as invalidate:
        source = await camera.stream_source()
    assert source is not None
    assert f"{PLAYLIST_PATH}/" in source
    assert source.endswith("/index.m3u8")
    invalidate.assert_called_once_with(camera._proxy_token)
    entry.runtime_data.client.async_allocate_stream.assert_not_awaited()


@pytest.mark.asyncio
async def test_healthy_hls_stream_does_not_reallocate_on_second_client() -> None:
    """Repeated clients during healthy playback reuse the cached playlist."""
    entry = _entry(dps_codes=("wireless_lowpower",))
    camera = await _camera_with_stream(entry, _stream(available=True))
    with patch.object(camera._proxy, "invalidate") as invalidate:
        source = await camera.stream_source()
    assert source is not None
    assert f"{PLAYLIST_PATH}/" in source
    invalidate.assert_not_called()


@pytest.mark.asyncio
async def test_low_power_function_code_also_selects_hls_proxy() -> None:
    """A low-power code exposed only as a function selects the proxy too."""
    entry = _entry()
    camera = await _setup_camera(entry)
    camera.coordinator.data["cam1"].functions = {
        "wireless_awake": MagicMock(),
        "wireless_powermode": MagicMock(),
    }
    source = await camera.stream_source()
    assert source is not None
    assert f"{PLAYLIST_PATH}/" in source
    entry.runtime_data.client.async_allocate_stream.assert_not_awaited()


@pytest.mark.asyncio
async def test_low_power_without_proxy_uses_direct_hls() -> None:
    """Without a proxy route the battery camera still gets a fresh HLS URL."""
    entry = _entry(dps_codes=("wireless_lowpower",))
    coordinator = entry.runtime_data
    coordinator.client.async_allocate_stream = AsyncMock(
        side_effect=lambda _id, kind: FALLBACK_URL if kind == "hls" else DIRECT_URL
    )
    camera = TuyaCamera(coordinator, coordinator.data["cam1"])
    assert await camera.stream_source() == FALLBACK_URL
    coordinator.client.async_allocate_stream.assert_awaited_once_with("cam1", "hls")


@pytest.mark.asyncio
async def test_single_power_code_keeps_rtsp() -> None:
    """A lone power-mode code must not misclassify a mains-powered camera."""
    entry = _entry(dps_codes=("wireless_powermode",))
    camera = await _setup_camera(entry)
    assert await camera.stream_source() == DIRECT_URL
    entry.runtime_data.client.async_allocate_stream.assert_awaited_once_with(
        "cam1", "rtsp"
    )


@pytest.mark.asyncio
async def test_explicit_non_lowpower_value_keeps_rtsp() -> None:
    """An explicit false low-power flag wins over the pair heuristic."""
    entry = _entry(
        dps_codes=("wireless_lowpower", "wireless_awake", "wireless_powermode")
    )
    camera = await _setup_camera(entry)
    camera.coordinator.data["cam1"].status["wireless_lowpower"] = False
    assert await camera.stream_source() == DIRECT_URL
    entry.runtime_data.client.async_allocate_stream.assert_awaited_once_with(
        "cam1", "rtsp"
    )


@pytest.mark.asyncio
async def test_rtsp_failure_falls_back_to_direct_hls() -> None:
    """A camera without the low-power codes tries the other stream type."""
    entry = _entry()
    coordinator = entry.runtime_data
    coordinator.client.async_allocate_stream = AsyncMock(
        side_effect=[TuyaApiError("denied"), FALLBACK_URL]
    )
    camera = TuyaCamera(coordinator, coordinator.data["cam1"])
    assert await camera.stream_source() == FALLBACK_URL
    coordinator.client.async_allocate_stream.assert_has_awaits(
        [call("cam1", "rtsp"), call("cam1", "hls")]
    )


@pytest.mark.asyncio
async def test_camera_uses_proxy_when_rtsp_fails() -> None:
    """A proxy-equipped camera falls back to its stable local playlist URL."""
    entry = _entry()
    coordinator = entry.runtime_data
    coordinator.client.async_allocate_stream = AsyncMock(
        side_effect=[TuyaApiError("denied"), TuyaApiError("denied")]
    )
    camera = await _setup_camera(entry)
    source = await camera.stream_source()
    assert source is not None
    assert f"{PLAYLIST_PATH}/" in source
    assert source.endswith("/index.m3u8")
    coordinator.client.async_allocate_stream.assert_has_awaits(
        [call("cam1", "rtsp"), call("cam1", "hls")]
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
        side_effect=[TuyaApiError("denied"), TuyaApiError("denied")]
    )
    coordinator = entry.runtime_data
    camera = TuyaCamera(coordinator, coordinator.data["cam1"])
    assert await camera.stream_source() is None


@pytest.mark.asyncio
async def test_expired_stream_source_is_renewed() -> None:
    """A failed worker gets a freshly allocated RTSP source."""
    entry = _entry()
    stream = _stream()
    camera = await _camera_with_stream(entry, stream)
    await camera._async_renew_stream_source()
    stream.update_source.assert_called_once_with(DIRECT_URL)
    entry.runtime_data.client.async_allocate_stream.assert_awaited_once_with(
        "cam1", "rtsp"
    )


@pytest.mark.asyncio
async def test_low_power_renewal_invalidates_proxy_allocation() -> None:
    """A stalled HLS worker reconnects to the same URL with a fresh playlist."""
    entry = _entry(dps_codes=("wireless_lowpower",))
    stream = _stream()
    camera = await _camera_with_stream(entry, stream)
    with patch.object(camera._proxy, "invalidate") as invalidate:
        await camera._async_renew_stream_source()
    invalidate.assert_called_once_with(camera._proxy_token)
    expected = camera._proxy.source_url(camera._proxy_token)
    stream.update_source.assert_called_once_with(expected)
    entry.runtime_data.client.async_allocate_stream.assert_not_awaited()


@pytest.mark.asyncio
async def test_offline_low_power_camera_does_not_renew() -> None:
    """An offline battery camera must not reconnect the proxy worker."""
    entry = _entry(dps_codes=("wireless_lowpower",), online=False)
    stream = _stream()
    camera = await _camera_with_stream(entry, stream)
    with patch.object(camera._proxy, "invalidate") as invalidate:
        await camera._async_renew_stream_source()
    invalidate.assert_not_called()
    stream.update_source.assert_not_called()
    entry.runtime_data.client.async_allocate_stream.assert_not_awaited()


@pytest.mark.asyncio
async def test_available_stream_is_not_renewed() -> None:
    """A healthy stream keeps its source and allocates nothing."""
    entry = _entry()
    stream = _stream(available=True)
    camera = await _camera_with_stream(entry, stream)
    await camera._async_renew_stream_source()
    stream.update_source.assert_not_called()
    entry.runtime_data.client.async_allocate_stream.assert_not_awaited()


@pytest.mark.asyncio
async def test_renewal_is_throttled_and_recovers_after_interval() -> None:
    """Repeated failures do not hammer the API, but still renew later."""
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
async def test_fallback_renewal_allocation_error_is_not_fatal() -> None:
    """A failed direct renewal leaves the stream untouched and raises nothing."""
    entry = _entry()
    entry.runtime_data.client.async_allocate_stream = AsyncMock(
        side_effect=[TuyaApiError("denied"), TuyaApiError("denied")]
    )
    coordinator = entry.runtime_data
    camera = TuyaCamera(coordinator, coordinator.data["cam1"])
    stream = _stream()
    camera.stream = stream
    await camera._async_renew_stream_source()
    stream.update_source.assert_not_called()


@pytest.mark.asyncio
async def test_offline_camera_does_not_renew() -> None:
    """An offline or stale device never triggers a stream renewal."""
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
    ):
        assert await camera.async_create_stream() is stream
        stream.set_update_callback.assert_called_once()
        callback = stream.set_update_callback.call_args.args[0]
        callback()
        camera.async_write_ha_state.assert_called_once()
        assert len(tasks) == 1
        await tasks[0]
    stream.update_source.assert_called_once_with(DIRECT_URL)


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
    stream.update_source.assert_called_once_with(DIRECT_URL)


@pytest.mark.asyncio
async def test_renewal_applies_source_if_worker_recovers_during_renewal() -> None:
    """A recovered worker must not cause the prepared source to be dropped."""
    entry = _entry()
    stream = _stream()
    camera = await _camera_with_stream(entry, stream)

    async def allocate() -> str:
        stream.available = True
        return DIRECT_URL

    with patch.object(camera, "_async_allocate_source", new=allocate):
        await camera._async_renew_stream_source()
    assert stream.update_source.call_count == 1


@pytest.mark.asyncio
async def test_renewal_does_not_touch_a_replaced_stream() -> None:
    """A source prepared for a detached stream is not applied to the new one."""
    entry = _entry()
    stream = _stream()
    camera = await _camera_with_stream(entry, stream)

    async def allocate() -> str:
        camera.stream = _stream()
        return DIRECT_URL

    with patch.object(camera, "_async_allocate_source", new=allocate):
        await camera._async_renew_stream_source()
    stream.update_source.assert_not_called()


def test_manifest_loads_ffmpeg_for_still_images() -> None:
    """The still-image path needs HA's ffmpeg manager to be set up."""
    manifest = (
        Path(__file__).parents[1]
        / "custom_components"
        / "tuya_project_cloud"
        / "manifest.json"
    )
    assert "ffmpeg" in json.loads(manifest.read_text(encoding="utf-8"))["dependencies"]


@pytest.mark.asyncio
async def test_camera_image_uses_fresh_source(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Still images use the same fresh source as upstream Tuya."""
    entry = _entry()
    camera = await _setup_camera(entry)
    get_image = AsyncMock(return_value=b"jpeg")
    with patch("homeassistant.components.ffmpeg.async_get_image", new=get_image):
        assert await camera.async_camera_image(320, 240) == b"jpeg"
    get_image.assert_awaited_once_with(camera.hass, DIRECT_URL, width=320, height=240)
    assert DIRECT_URL not in caplog.text


@pytest.mark.asyncio
async def test_camera_image_without_source_returns_none() -> None:
    """No allocation means no image, without calling ffmpeg."""
    entry = _entry(online=False)
    camera = await _setup_camera(entry)
    get_image = AsyncMock(return_value=b"jpeg")
    with patch("homeassistant.components.ffmpeg.async_get_image", new=get_image):
        assert await camera.async_camera_image() is None
    get_image.assert_not_awaited()


@pytest.mark.asyncio
async def test_camera_image_does_not_detach_unavailable_stream() -> None:
    """A snapshot must leave an existing stream worker attached."""
    entry = _entry()
    stream = _stream()
    camera = await _camera_with_stream(entry, stream)
    get_image = AsyncMock(return_value=b"jpeg")
    with patch("homeassistant.components.ffmpeg.async_get_image", new=get_image):
        assert await camera.async_camera_image() == b"jpeg"
    assert camera.stream is stream
    get_image.assert_awaited_once()


@pytest.mark.asyncio
async def test_camera_image_ffmpeg_error_is_not_swallowed() -> None:
    """A real ffmpeg failure stays visible to HA's image endpoint."""
    entry = _entry()
    camera = await _setup_camera(entry)
    get_image = AsyncMock(side_effect=RuntimeError("ffmpeg failed"))
    with (
        patch("homeassistant.components.ffmpeg.async_get_image", new=get_image),
        pytest.raises(RuntimeError),
    ):
        await camera.async_camera_image()


@pytest.mark.asyncio
async def test_renewal_logs_no_url_or_device_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Even debug messages must not expose a URL or device identifier."""
    entry = _entry()
    entry.runtime_data.client.async_allocate_stream = AsyncMock(
        side_effect=[TuyaApiError("denied"), TuyaApiError("denied")]
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
    assert FALLBACK_URL not in caplog.text
