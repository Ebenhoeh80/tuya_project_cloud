"""Tests for the local HLS stream proxy."""

from __future__ import annotations

import logging
import re
import time
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import web

from custom_components.tuya_project_cloud.api import TuyaApiError, TuyaDevice
from custom_components.tuya_project_cloud.hls_ts import (
    _write_pcr,
    _write_timestamp,
    decrypt,
    encrypt,
    timestamps,
)
from custom_components.tuya_project_cloud.stream_proxy import (
    BODY_TTL,
    RESOURCE_TTL,
    TuyaKeyView,
    TuyaPlaylistView,
    TuyaSegmentView,
    TuyaStreamProxy,
    _SegmentMeta,
    async_register_stream_proxy,
)

UPSTREAM = "https://upstream.invalid/live/index.m3u8?signInfo=TOPSECRET"
PLAYLIST = (
    "#EXTM3U\n"
    "#EXT-X-VERSION:4\n"
    '#EXT-X-KEY:METHOD=AES-128,URI="key.bin?token=KEYTOKEN",IV=0x1234\n'
    "#EXT-X-MEDIA-SEQUENCE:1\n"
    "#EXT-X-TARGETDURATION:4\n"
    "#EXTINF:4.0,\n"
    "segment1.ts?token=SEGTOKEN\n"
    "#EXTINF:4.0,\n"
    "segment2.ts?token=SEGTOKEN2\n"
)


def _proxy() -> tuple[TuyaStreamProxy, str, AsyncMock]:
    """Return a proxy with one registered camera."""
    hass = MagicMock()
    coordinator = MagicMock()
    device = TuyaDevice(
        id="cam1",
        name="Door viewer",
        category="sp",
        product_id="p1",
        online=True,
        last_update_success=True,
    )
    coordinator.client.async_allocate_stream = AsyncMock(return_value=UPSTREAM)
    proxy = TuyaStreamProxy(hass)
    token = proxy.register(device.id, coordinator)
    return proxy, token, coordinator.client.async_allocate_stream


def _response(
    body: bytes, *, status: int = 200, headers: dict[str, str] | None = None
) -> MagicMock:
    """Return a mock aiohttp response usable as an async context manager."""
    response = MagicMock()
    response.status = status
    response.headers = headers or {}
    response.read = AsyncMock(return_value=body)
    response.__aenter__ = AsyncMock(return_value=response)
    response.__aexit__ = AsyncMock(return_value=False)
    return response


def _growing_playlist(segments: int, prefix: str = "segment") -> str:
    """Return a Tuya-style playlist whose segment list only grows."""
    lines = [
        "#EXTM3U",
        "#EXT-X-VERSION:4",
        '#EXT-X-KEY:METHOD=AES-128,URI="key.bin?token=KEYTOKEN",IV=0x1234',
        "#EXT-X-MEDIA-SEQUENCE:0",
        "#EXT-X-TARGETDURATION:3",
        "#EXT-X-DISCONTINUITY",
    ]
    for index in range(segments):
        lines.extend(("#EXTINF:2.0,", f"{prefix}{index}.ts?token=SEGTOKEN"))
    return "\n".join(lines) + "\n"


def _segment_paths(playlist: str | None) -> list[str]:
    """Return only the segment URLs of a rewritten playlist."""
    assert playlist is not None
    return [line for line in playlist.splitlines() if line and not line.startswith("#")]


@pytest.mark.asyncio
async def test_playlist_hides_all_signed_upstream_urls() -> None:
    """The rewritten playlist contains only opaque local URLs."""
    proxy, token, allocate = _proxy()
    session = MagicMock()
    session.get = MagicMock(
        side_effect=[
            _response(PLAYLIST.encode()),
            _response(b"segment-bytes", headers={"Content-Type": "video/mp2ts"}),
            _response(
                b"key-bytes", headers={"Content-Type": "application/octet-stream"}
            ),
        ]
    )
    with (
        patch(
            "custom_components.tuya_project_cloud.stream_proxy.async_get_clientsession",
            return_value=session,
        ),
        patch(
            "custom_components.tuya_project_cloud.stream_proxy.get_url",
            return_value="http://ha.invalid:8123",
        ),
    ):
        playlist = await proxy.playlist(token)
        assert playlist is not None
        assert "upstream.invalid" not in playlist
        assert "signInfo" not in playlist
        assert "KEYTOKEN" not in playlist
        assert "SEGTOKEN" not in playlist
        assert "#EXT-X-KEY" in playlist
        key_path = re.search(r'URI="([^"]+)"', playlist).group(1)
        segment_path = next(
            line for line in playlist.splitlines() if line and not line.startswith("#")
        )
        segment = await proxy.resource(
            token, "segment", segment_path.rsplit("/", 1)[-1].removesuffix(".ts")
        )
        key = await proxy.resource(
            token, "key", key_path.rsplit("/", 1)[-1].removesuffix(".key")
        )
    assert segment is not None and segment[0] == b"segment-bytes"
    assert key is not None and key[0] == b"key-bytes"
    allocate.assert_awaited_once_with("cam1", "hls")


@pytest.mark.asyncio
async def test_allocation_is_cached_until_invalidated() -> None:
    """A playlist refresh reuses one signed URL until renewal is requested."""
    proxy, token, allocate = _proxy()
    with patch(
        "custom_components.tuya_project_cloud.stream_proxy.async_get_clientsession",
        return_value=MagicMock(
            get=MagicMock(return_value=_response(PLAYLIST.encode()))
        ),
    ):
        first = await proxy.playlist(token)
        second = await proxy.playlist(token)
        proxy.invalidate(token)
        third = await proxy.playlist(token)
    assert first == second
    assert third is not None
    assert allocate.await_count == 2


@pytest.mark.asyncio
async def test_failed_playlist_forces_one_fresh_allocation() -> None:
    """An upstream error triggers exactly one re-allocation."""
    proxy, token, allocate = _proxy()
    session = MagicMock()
    session.get = MagicMock(
        side_effect=[
            _response(b"", status=503),
            _response(PLAYLIST.encode()),
        ]
    )
    with patch(
        "custom_components.tuya_project_cloud.stream_proxy.async_get_clientsession",
        return_value=session,
    ):
        playlist = await proxy.playlist(token)
    assert playlist is not None
    assert allocate.await_count == 2


@pytest.mark.asyncio
async def test_unknown_token_has_no_playlist_or_resource() -> None:
    """An unknown token cannot be used to reach any upstream URL."""
    proxy, _, _ = _proxy()
    assert await proxy.playlist("unknown") is None
    assert await proxy.resource("unknown", "segment", "x") is None
    assert "unknown" not in proxy._playlist_state
    assert "unknown" not in proxy._locks
    proxy.unregister("cam1")
    assert await proxy.playlist("unknown") is None


@pytest.mark.asyncio
async def test_views_return_404_without_revealing_upstream() -> None:
    """The HTTP views fail closed for unknown tokens."""
    proxy, _, _ = _proxy()
    views = (
        TuyaPlaylistView(proxy),
        TuyaSegmentView(proxy),
        TuyaKeyView(proxy),
    )
    for view in views:
        if isinstance(view, TuyaPlaylistView):
            response = await view.get(MagicMock(), "unknown")
        else:
            response = await view.get(MagicMock(), "unknown", "x")
        assert isinstance(response, web.Response)
        assert response.status == 404
        assert "upstream.invalid" not in response.text


@pytest.mark.asyncio
async def test_source_url_is_stable_and_opaque() -> None:
    """The source URL stays identical across calls and hides the device ID."""
    proxy, token, _ = _proxy()
    with patch(
        "custom_components.tuya_project_cloud.stream_proxy.get_url",
        return_value="http://ha.invalid:8123",
    ):
        first = proxy.source_url(token)
        second = proxy.source_url(token)
    assert first == second
    assert "cam1" not in first
    assert first.endswith(f"{token}/index.m3u8")


@pytest.mark.asyncio
async def test_invalidation_keeps_inflight_resources() -> None:
    """A renewal does not break clients still reading the previous playlist."""
    proxy, token, allocate = _proxy()
    session = MagicMock()
    session.get = MagicMock(
        side_effect=[
            _response(PLAYLIST.encode()),
            _response(b"segment-bytes"),
            _response(PLAYLIST.encode()),
        ]
    )
    with (
        patch(
            "custom_components.tuya_project_cloud.stream_proxy.get_url",
            return_value="http://ha.invalid:8123",
        ),
        patch(
            "custom_components.tuya_project_cloud.stream_proxy.async_get_clientsession",
            return_value=session,
        ),
    ):
        playlist = await proxy.playlist(token)
        segment_path = next(
            line for line in playlist.splitlines() if line and not line.startswith("#")
        )
        resource_id = segment_path.rsplit("/", 1)[-1].removesuffix(".ts")
        proxy.invalidate(token)
        resource = await proxy.resource(token, "segment", resource_id)
        assert await proxy.playlist(token) is not None
    assert resource is not None and resource[0] == b"segment-bytes"
    assert allocate.await_count == 2


@pytest.mark.asyncio
async def test_ttl_prunes_allocations_and_resources() -> None:
    """Expired allocations and resources are dropped automatically."""
    proxy, token, allocate = _proxy()
    session = MagicMock()
    session.get = MagicMock(
        side_effect=[_response(PLAYLIST.encode()), _response(PLAYLIST.encode())]
    )
    with (
        patch("custom_components.tuya_project_cloud.stream_proxy.ALLOCATION_TTL", 0.0),
        patch("custom_components.tuya_project_cloud.stream_proxy.RESOURCE_TTL", 0.0),
        patch(
            "custom_components.tuya_project_cloud.stream_proxy.async_get_clientsession",
            return_value=session,
        ),
    ):
        first = await proxy.playlist(token)
        segment_path = next(
            line for line in first.splitlines() if line and not line.startswith("#")
        )
        resource_id = segment_path.rsplit("/", 1)[-1].removesuffix(".ts")
        assert await proxy.resource(token, "segment", resource_id) is None
        assert await proxy.playlist(token) is not None
    assert allocate.await_count == 2


@pytest.mark.asyncio
async def test_views_serve_rewritten_playlist_segments_and_keys() -> None:
    """The registered views return 200 responses without upstream URLs."""
    proxy, token, _ = _proxy()
    session = MagicMock()
    session.get = MagicMock(
        side_effect=[
            _response(PLAYLIST.encode()),
            _response(b"segment-bytes", headers={"Content-Type": "video/mp2ts"}),
            _response(
                b"key-bytes", headers={"Content-Type": "application/octet-stream"}
            ),
        ]
    )
    with (
        patch(
            "custom_components.tuya_project_cloud.stream_proxy.get_url",
            return_value="http://ha.invalid:8123",
        ),
        patch(
            "custom_components.tuya_project_cloud.stream_proxy.async_get_clientsession",
            return_value=session,
        ),
    ):
        playlist_response = await TuyaPlaylistView(proxy).get(MagicMock(), token)
        playlist = playlist_response.text
        segment_path = next(
            line for line in playlist.splitlines() if line and not line.startswith("#")
        )
        key_path = re.search(r'URI="([^"]+)"', playlist).group(1)
        segment_response = await TuyaSegmentView(proxy).get(
            MagicMock(), token, segment_path.rsplit("/", 1)[-1]
        )
        key_response = await TuyaKeyView(proxy).get(
            MagicMock(), token, key_path.rsplit("/", 1)[-1]
        )
    assert playlist_response.status == 200
    assert segment_response.status == 200 and segment_response.body == b"segment-bytes"
    assert key_response.status == 200 and key_response.body == b"key-bytes"
    assert "upstream.invalid" not in playlist


def test_registration_is_idempotent_and_needs_no_user_token() -> None:
    """Proxy views are registered once and are reachable by HA's stream worker."""
    hass = MagicMock()
    hass.data = {}
    first = async_register_stream_proxy(hass)
    second = async_register_stream_proxy(hass)
    views = [call.args[0] for call in hass.http.register_view.call_args_list]
    assert first is second
    assert len(views) == 3
    assert all(view.requires_auth is False for view in views)


@pytest.mark.asyncio
async def test_resources_are_bound_to_their_proxy_token() -> None:
    """A resource registered for one camera cannot be read with another token."""
    proxy, token, _ = _proxy()
    coordinator = proxy._routes[token][1]
    other_token = proxy.register("cam2", coordinator)
    session = MagicMock()
    session.get = MagicMock(return_value=_response(PLAYLIST.encode()))
    with (
        patch(
            "custom_components.tuya_project_cloud.stream_proxy.get_url",
            return_value="http://ha.invalid:8123",
        ),
        patch(
            "custom_components.tuya_project_cloud.stream_proxy.async_get_clientsession",
            return_value=session,
        ),
    ):
        playlist = await proxy.playlist(token)
        segment_path = next(
            line for line in playlist.splitlines() if line and not line.startswith("#")
        )
        resource_id = segment_path.rsplit("/", 1)[-1].removesuffix(".ts")
        assert await proxy.resource(other_token, "segment", resource_id) is None


@pytest.mark.asyncio
async def test_unregister_coordinator_forgets_all_cameras() -> None:
    """Unloading a config entry removes all of its proxy routes."""
    proxy, token, _ = _proxy()
    coordinator = proxy._routes[token][1]
    other_token = proxy.register("cam2", coordinator)
    proxy.unregister_coordinator(coordinator)
    assert await proxy.playlist(token) is None
    assert await proxy.playlist(other_token) is None


@pytest.mark.asyncio
async def test_proxy_never_logs_upstream_urls_or_keys(caplog) -> None:
    """Debug logging does not leak signed URLs or AES key values."""
    proxy, token, _ = _proxy()
    session = MagicMock()
    session.get = MagicMock(return_value=_response(PLAYLIST.encode()))
    caplog.set_level(
        logging.DEBUG, logger="custom_components.tuya_project_cloud.stream_proxy"
    )
    with (
        patch(
            "custom_components.tuya_project_cloud.stream_proxy.async_get_clientsession",
            return_value=session,
        ),
        patch(
            "custom_components.tuya_project_cloud.stream_proxy.get_url",
            return_value="http://ha.invalid:8123",
        ),
    ):
        assert await proxy.playlist(token) is not None
    assert "upstream.invalid" not in caplog.text
    assert "KEYTOKEN" not in caplog.text
    assert "SEGTOKEN" not in caplog.text


@pytest.mark.asyncio
async def test_playlist_uses_sliding_window_with_advancing_sequence() -> None:
    """Tuya's growing segment list becomes a bounded live HLS window."""
    proxy, token, allocate = _proxy()
    session = MagicMock()
    session.get = MagicMock(
        side_effect=[
            _response(_growing_playlist(2).encode()),
            _response(_growing_playlist(5).encode()),
            _response(_growing_playlist(7).encode()),
        ]
    )
    with (
        patch(
            "custom_components.tuya_project_cloud.stream_proxy.async_get_clientsession",
            return_value=session,
        ),
        patch(
            "custom_components.tuya_project_cloud.stream_proxy.get_url",
            return_value="http://ha.invalid:8123",
        ),
    ):
        first = await proxy.playlist(token)
        second = await proxy.playlist(token)
        third = await proxy.playlist(token)

    def segments(playlist: str | None) -> list[str]:
        assert playlist is not None
        return [
            line for line in playlist.splitlines() if line and not line.startswith("#")
        ]

    assert "#EXT-X-VERSION:6" in first
    assert "#EXT-X-DISCONTINUITY-SEQUENCE:0" in third
    assert "#EXT-X-MEDIA-SEQUENCE:0" in first
    assert "#EXT-X-MEDIA-SEQUENCE:1" in second
    assert "#EXT-X-MEDIA-SEQUENCE:3" in third
    assert len(segments(first)) == 2
    assert len(segments(second)) == 4
    assert len(segments(third)) == 4
    assert segments(second)[0] != segments(first)[0]
    assert segments(third)[0] != segments(second)[0]
    assert "#EXT-X-DISCONTINUITY" not in (third or "").splitlines()
    assert "SEGTOKEN" not in third
    assert "KEYTOKEN" not in third
    assert allocate.await_count == 1


@pytest.mark.asyncio
async def test_allocation_change_bridges_old_and_new_segments() -> None:
    """A renewed Tuya session does not reuse a sequence for a new segment."""
    proxy, token, allocate = _proxy()
    old_source = "https://upstream.invalid/live/old.m3u8?signInfo=OLD"
    new_source = "https://upstream.invalid/live/new.m3u8?signInfo=NEW"
    allocate.side_effect = [old_source, new_source]
    session = MagicMock()
    session.get = MagicMock(
        side_effect=[
            _response(_growing_playlist(2).encode()),
            _response(_growing_playlist(2, prefix="renewed").encode()),
            _response(_growing_playlist(4, prefix="renewed").encode()),
        ]
    )
    with (
        patch(
            "custom_components.tuya_project_cloud.stream_proxy.async_get_clientsession",
            return_value=session,
        ),
        patch(
            "custom_components.tuya_project_cloud.stream_proxy.get_url",
            return_value="http://ha.invalid:8123",
        ),
    ):
        first = await proxy.playlist(token)
        proxy.invalidate(token)
        second = await proxy.playlist(token)
        third = await proxy.playlist(token)

    first_paths = _segment_paths(first)
    second_paths = _segment_paths(second)
    assert "#EXT-X-VERSION:6" in first
    assert "#EXT-X-DISCONTINUITY-SEQUENCE:0" in (second or "")
    assert first_paths[0] in second_paths
    assert second is not None
    assert "#EXT-X-DISCONTINUITY" in second.splitlines()
    new_paths = [path for path in second_paths if path not in first_paths]
    assert len(new_paths) == 2
    assert second.index("#EXT-X-DISCONTINUITY") < second.index(new_paths[0])
    assert first_paths[0] not in _segment_paths(third)
    assert "#EXT-X-DISCONTINUITY-SEQUENCE:1" in (third or "")
    assert "#EXT-X-DISCONTINUITY" in (third or "").splitlines()
    assert allocate.await_count == 2


@pytest.mark.asyncio
async def test_frozen_playlist_forces_fresh_allocation() -> None:
    """A reachable playlist that stops growing is renewed proactively."""
    proxy, token, allocate = _proxy()
    session = MagicMock()
    session.get = MagicMock(
        side_effect=[
            _response(PLAYLIST.encode()),
            _response(PLAYLIST.encode()),
            _response(PLAYLIST.encode()),
        ]
    )
    with (
        patch(
            "custom_components.tuya_project_cloud.stream_proxy.async_get_clientsession",
            return_value=session,
        ),
        patch(
            "custom_components.tuya_project_cloud.stream_proxy.PLAYLIST_STALE_TIMEOUT",
            0.0,
        ),
    ):
        assert await proxy.playlist(token) is not None
        assert await proxy.playlist(token) is not None
    assert allocate.await_count == 2


@pytest.mark.asyncio
async def test_playlist_keeps_key_rewrite_in_sliding_window() -> None:
    """The AES key stays local even after the window advances."""
    proxy, token, _ = _proxy()
    session = MagicMock()
    session.get = MagicMock(
        side_effect=[
            _response(_growing_playlist(2).encode()),
            _response(_growing_playlist(6).encode()),
        ]
    )
    with (
        patch(
            "custom_components.tuya_project_cloud.stream_proxy.async_get_clientsession",
            return_value=session,
        ),
        patch(
            "custom_components.tuya_project_cloud.stream_proxy.get_url",
            return_value="http://ha.invalid:8123",
        ),
    ):
        await proxy.playlist(token)
        playlist = await proxy.playlist(token)
    assert playlist is not None
    key_path = re.search(r'URI="([^"]+)"', playlist).group(1)
    assert key_path.startswith("http://ha.invalid:8123/api/")
    assert "upstream.invalid" not in playlist


@pytest.mark.asyncio
async def test_allocation_failure_is_cooldown_limited() -> None:
    """Repeated playlist requests do not spam Tuya after an allocation failure."""
    proxy, token, allocate = _proxy()
    allocate.side_effect = TuyaApiError("denied")
    assert await proxy.playlist(token) is None
    assert await proxy.playlist(token) is None
    assert allocate.await_count == 1


@pytest.mark.asyncio
async def test_discontinuity_sequence_header_is_not_a_tag() -> None:
    """An upstream DSEQ header must not mark the next segment as a new session."""
    proxy, token, _ = _proxy()
    upstream = (
        b"#EXTM3U\n"
        b"#EXT-X-VERSION:6\n"
        b"#EXT-X-DISCONTINUITY-SEQUENCE:7\n"
        b"#EXT-X-TARGETDURATION:3\n"
        b"#EXTINF:2.0,\n"
        b"segment0.ts?token=SEGTOKEN\n"
    )
    session = MagicMock()
    session.get = MagicMock(return_value=_response(upstream))
    with patch(
        "custom_components.tuya_project_cloud.stream_proxy.async_get_clientsession",
        return_value=session,
    ):
        playlist = await proxy.playlist(token)
    assert playlist is not None
    assert "#EXT-X-DISCONTINUITY" not in playlist.splitlines()
    assert "#EXT-X-DISCONTINUITY-SEQUENCE:0" in playlist


@pytest.mark.asyncio
async def test_empty_renewed_playlist_keeps_discontinuity_pending() -> None:
    """A new session with no segments yet still gets exactly one discontinuity."""
    proxy, token, allocate = _proxy()
    allocate.side_effect = [
        "https://upstream.invalid/live/old.m3u8?signInfo=OLD",
        "https://upstream.invalid/live/new.m3u8?signInfo=NEW",
    ]
    session = MagicMock()
    session.get = MagicMock(
        side_effect=[
            _response(_growing_playlist(2).encode()),
            _response(b"#EXTM3U\n#EXT-X-TARGETDURATION:3\n"),
            _response(_growing_playlist(2, prefix="renewed").encode()),
        ]
    )
    with patch(
        "custom_components.tuya_project_cloud.stream_proxy.async_get_clientsession",
        return_value=session,
    ):
        first = await proxy.playlist(token)
        proxy.invalidate(token)
        middle = await proxy.playlist(token)
        third = await proxy.playlist(token)
    assert middle is not None and third is not None

    def tags(playlist: str) -> int:
        return sum(line == "#EXT-X-DISCONTINUITY" for line in playlist.splitlines())

    assert tags(middle) == 1
    assert tags(third) == 2
    assert "#EXT-X-DISCONTINUITY-SEQUENCE:0" in third
    assert _segment_paths(first)[0] in _segment_paths(third)


@pytest.mark.asyncio
async def test_stale_allocation_does_not_rewrite_window() -> None:
    """A late request with an older allocation returns the last valid playlist."""
    proxy, token, allocate = _proxy()
    session = MagicMock()
    session.get = MagicMock(return_value=_response(_growing_playlist(3).encode()))
    with patch(
        "custom_components.tuya_project_cloud.stream_proxy.async_get_clientsession",
        return_value=session,
    ):
        first = await proxy.playlist(token)
        proxy._playlist_state[token].generation += 1
        second = await proxy.playlist(token)
    assert second == first
    assert allocate.await_count == 1


@pytest.mark.asyncio
async def test_key_uri_stays_stable_across_polls() -> None:
    """An unchanged upstream key keeps its local URI between playlist polls."""
    proxy, token, _ = _proxy()
    session = MagicMock()
    session.get = MagicMock(return_value=_response(PLAYLIST.encode()))
    with patch(
        "custom_components.tuya_project_cloud.stream_proxy.async_get_clientsession",
        return_value=session,
    ):
        first = await proxy.playlist(token)
        second = await proxy.playlist(token)
    assert first is not None and second is not None
    key = re.compile(r'URI="([^"]+)"')
    assert key.search(first).group(1) == key.search(second).group(1)


def _ts_packet(pcr: int, dts: int | None) -> bytes:
    """Return one TS packet with PCR and an optional PES DTS."""
    packet = bytearray(188)
    packet[0] = 0x47
    packet[1] = 0x40 if dts is not None else 0x00
    packet[3] = 0x30
    packet[4] = 7
    packet[5] = 0x10
    _write_pcr(packet, 6, pcr)
    if dts is not None:
        packet[12:15] = b"\x00\x00\x01"
        packet[15] = 0xE0
        packet[19] = 0xC0
        packet[20] = 10
        _write_timestamp(packet, 21, dts)
        _write_timestamp(packet, 26, dts)
    return bytes(packet)


def _encrypted_segment(start: float) -> bytes:
    """Build an AES-128 segment whose timestamps restart at ``start``."""
    base = int(start * 90000)
    clear = b"".join(
        _ts_packet(base + index * 3600, base if index == 0 else None)
        for index in range(4)
    )
    encrypted = encrypt(clear, bytes(range(16)), bytes(range(16, 32)))
    assert encrypted is not None
    return encrypted


@pytest.mark.asyncio
async def test_encrypted_segments_get_continuous_timestamps_across_allocations() -> (
    None
):
    """A fresh Tuya allocation must not make HA see a 30 s DTS jump."""
    proxy, token, _ = _proxy()
    rebase_playlist = PLAYLIST.replace(
        "IV=0x1234", "IV=0x101112131415161718191a1b1c1d1e1f"
    )
    first_playlist = rebase_playlist.replace("segment1.ts", "old.ts").replace(
        "segment2.ts?token=SEGTOKEN2", ""
    )
    second_playlist = rebase_playlist.replace("segment1.ts", "new.ts").replace(
        "segment2.ts?token=SEGTOKEN2", ""
    )
    first_segment = _encrypted_segment(31.5)
    second_segment = _encrypted_segment(1.5)
    polls = 0

    async def fake_fetch(url: str) -> tuple[bytes, dict[str, str]] | None:
        nonlocal polls
        if url == UPSTREAM:
            polls += 1
            return (first_playlist if polls == 1 else second_playlist).encode(), {}
        if "key.bin" in url:
            return bytes(range(16)), {}
        if "old.ts" in url:
            return first_segment, {}
        if "new.ts" in url:
            return second_segment, {}
        return None

    with (
        patch.object(proxy, "_fetch", side_effect=fake_fetch),
        patch(
            "custom_components.tuya_project_cloud.stream_proxy.get_url",
            return_value="http://ha.invalid:8123",
        ),
    ):
        first_playlist_text = await proxy.playlist(token)
        proxy.invalidate(token)
        second_playlist_text = await proxy.playlist(token)
        assert first_playlist_text is not None and second_playlist_text is not None
        first_resource = _segment_paths(first_playlist_text)[0].rsplit("/", 1)[-1]
        second_resource = _segment_paths(second_playlist_text)[-1].rsplit("/", 1)[-1]
        first_body = await proxy.resource(
            token, "segment", first_resource.removesuffix(".ts")
        )
        second_body = await proxy.resource(
            token, "segment", second_resource.removesuffix(".ts")
        )

    assert first_body is not None and second_body is not None
    first_clear = decrypt(first_body[0], bytes(range(16)), bytes(range(16, 32)))
    second_clear = decrypt(second_body[0], bytes(range(16)), bytes(range(16, 32)))
    assert first_clear is not None and second_clear is not None
    _, first_last = timestamps(first_clear)
    second_first, _ = timestamps(second_clear)
    assert first_last is not None and second_first is not None
    assert second_first > first_last
    assert second_first - first_last < 90000


@pytest.mark.asyncio
async def test_next_dts_wraps_across_33_bits() -> None:
    """A new allocation after the PTS wrap must not reset to the old high value."""
    proxy, token, _ = _proxy()
    segment = _encrypted_segment(((1 << 33) - 2000) / 90000)
    meta = _SegmentMeta(generation=1, key_url="key.bin", iv=bytes(range(16, 32)))

    async def fake_fetch(url: str) -> tuple[bytes, dict[str, str]] | None:
        if url == UPSTREAM:
            return PLAYLIST.encode(), {}
        return bytes(range(16)), {}

    with patch.object(proxy, "_fetch", side_effect=fake_fetch):
        await proxy.playlist(token)
        state = proxy._playlist_state[token]
        state.next_dts = 1000
        state.rebased_generation = 0
        _, cacheable = await proxy._rebase_segment(token, segment, meta)

    assert cacheable
    assert state.next_dts is not None
    assert 0 <= state.next_dts < 100000


@pytest.mark.asyncio
async def test_rebased_segment_bodies_are_bounded() -> None:
    """Bodies expire quickly; expired resources drop their metadata too."""
    proxy, token, _ = _proxy()
    playlist = PLAYLIST.replace("IV=0x1234", "IV=0x101112131415161718191a1b1c1d1e1f")
    segment = _encrypted_segment(31.5)
    fetches = 0

    async def fake_fetch(url: str) -> tuple[bytes, dict[str, str]] | None:
        nonlocal fetches
        if url == UPSTREAM:
            return playlist.encode(), {}
        if "key.bin" in url:
            return bytes(range(16)), {}
        if "segment1.ts" in url:
            fetches += 1
            return segment, {}
        return None

    with (
        patch.object(proxy, "_fetch", side_effect=fake_fetch),
        patch(
            "custom_components.tuya_project_cloud.stream_proxy.get_url",
            return_value="http://ha.invalid:8123",
        ),
    ):
        text = await proxy.playlist(token)
        assert text is not None
        resource_id = _segment_paths(text)[0].rsplit("/", 1)[-1].removesuffix(".ts")
        key = f"{token}:segment:{resource_id}"
        first = await proxy.resource(token, "segment", resource_id)
        second = await proxy.resource(token, "segment", resource_id)
        assert first is not None and second is not None
        assert fetches == 1
        assert second[0] == first[0]

        proxy._resources[key] = replace(
            proxy._resources[key], body_created=time.monotonic() - BODY_TTL - 1
        )
        proxy._prune()
        assert proxy._resources[key].body is None
        await proxy.resource(token, "segment", resource_id)
        assert fetches == 2

        proxy._resources[key] = replace(
            proxy._resources[key], created=time.monotonic() - RESOURCE_TTL - 1
        )
        proxy._prune()
        assert key not in proxy._resources
        assert key not in proxy._segment_meta


@pytest.mark.asyncio
async def test_failed_rebase_is_not_cached() -> None:
    """A segment that could not be rebased must be retried on the next read."""
    proxy, token, _ = _proxy()
    segment = _encrypted_segment(1.5)

    async def fake_fetch(url: str) -> tuple[bytes, dict[str, str]] | None:
        if url == UPSTREAM:
            return PLAYLIST.encode(), {}
        if "segment1.ts" in url:
            return segment, {}
        return None

    with (
        patch.object(proxy, "_fetch", side_effect=fake_fetch),
        patch.object(proxy, "_rebase_segment", return_value=(segment, False)),
        patch(
            "custom_components.tuya_project_cloud.stream_proxy.get_url",
            return_value="http://ha.invalid:8123",
        ),
    ):
        text = await proxy.playlist(token)
        assert text is not None
        resource_id = _segment_paths(text)[0].rsplit("/", 1)[-1].removesuffix(".ts")
        body = await proxy.resource(token, "segment", resource_id)

    assert body is not None and body[0] == segment
    assert proxy._resources[f"{token}:segment:{resource_id}"].body is None


@pytest.mark.asyncio
async def test_resource_is_not_stored_after_unload() -> None:
    """An in-flight rebase must not resurrect a forgotten token."""
    proxy, token, _ = _proxy()

    async def fake_fetch(url: str) -> tuple[bytes, dict[str, str]] | None:
        if url == UPSTREAM:
            return PLAYLIST.encode(), {}
        if "segment1.ts" in url:
            return b"segment-bytes" * 30, {}
        return None

    async def forget_during_rebase(
        current_token: str, encrypted: bytes, meta: object
    ) -> tuple[bytes, bool]:
        proxy._forget(current_token)
        return encrypted, True

    with (
        patch.object(proxy, "_fetch", side_effect=fake_fetch),
        patch.object(proxy, "_rebase_segment", side_effect=forget_during_rebase),
        patch(
            "custom_components.tuya_project_cloud.stream_proxy.get_url",
            return_value="http://ha.invalid:8123",
        ),
    ):
        text = await proxy.playlist(token)
        assert text is not None
        resource_id = _segment_paths(text)[0].rsplit("/", 1)[-1].removesuffix(".ts")
        assert await proxy.resource(token, "segment", resource_id) is None

    assert f"{token}:segment:{resource_id}" not in proxy._resources


@pytest.mark.asyncio
async def test_playlist_without_explicit_iv_is_not_rebased() -> None:
    """A guessed IV would break decryption, so no metadata is stored."""
    proxy, token, _ = _proxy()
    playlist = PLAYLIST.replace(",IV=0x1234", "")

    async def fake_fetch(url: str) -> tuple[bytes, dict[str, str]] | None:
        if url == UPSTREAM:
            return playlist.encode(), {}
        return None

    with (
        patch.object(proxy, "_fetch", side_effect=fake_fetch),
        patch(
            "custom_components.tuya_project_cloud.stream_proxy.get_url",
            return_value="http://ha.invalid:8123",
        ),
    ):
        assert await proxy.playlist(token) is not None

    assert not proxy._segment_meta
