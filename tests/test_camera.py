"""Tests for the camera platform."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.components.camera import CameraEntityFeature

from custom_components.tuya_project_cloud.api import TuyaApiError, TuyaDevice
from custom_components.tuya_project_cloud.camera import (
    async_setup_entry as camera_setup,
)


def _entry(*, online: bool = True, enabled: bool = True) -> MagicMock:
    """Return an entry with one mocked camera device."""
    device = TuyaDevice(
        id="cam1",
        name="Door viewer",
        category="sp",
        product_id="p1",
        online=online,
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
