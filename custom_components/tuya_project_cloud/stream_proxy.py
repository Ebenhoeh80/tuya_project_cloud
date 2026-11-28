"""Local HLS reverse proxy for short-lived Tuya stream URLs.

Home Assistant and go2rtc get one stable local URL per camera. The proxy keeps
the signed Tuya URLs and encryption keys in memory, renews them transparently
and never writes them to logs, entity attributes or diagnostics.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import secrets
import time
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING
from urllib.parse import urljoin

from aiohttp import ClientError, ClientTimeout, web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.network import NoURLAvailableError, get_url

from .api import TuyaApiError
from .const import DOMAIN
from .hls_ts import decrypt, encrypt, shift, timestamps
from .utils import redact_identifier

if TYPE_CHECKING:
    from .coordinator import TuyaProjectCloudCoordinator

_LOGGER = logging.getLogger(__name__)

PLAYLIST_PATH = f"/api/{DOMAIN}/stream"
# Tuya's signed HLS session stopped producing new segments after roughly
# 40 s in live probes, so renew before that even if the URL still responds.
ALLOCATION_TTL = 30.0
RESOURCE_TTL = 600.0
# Rebasing copies a whole segment into memory. Keep bodies only as long as a
# client may replay the last few chunks; URLs stay available for RESOURCE_TTL.
BODY_TTL = 60.0
ALLOCATION_FAILURE_COOLDOWN = 10.0
FETCH_TIMEOUT = ClientTimeout(total=15)
FALLBACK_BASE_URL = "http://localhost:8123"
# Tuya's playlist keeps every segment while its MEDIA-SEQUENCE stays at 0.
# FFmpeg treats the repeated segments as new on each reload, which produces
# corrupt packets and ends the worker. Serve a conventional sliding window.
PLAYLIST_WINDOW = 4
# Tuya can leave a signed playlist reachable but frozen when its session
# expires. Without a fetch error the worker would simply run out of segments.
PLAYLIST_STALE_TIMEOUT = 30.0
# One video frame at 25 fps, used to connect consecutive segments.
FRAME_TICKS = 90000 // 25
_KEY_URI_RE = re.compile(r'(URI=")([^"]+)(")')
_KEY_METHOD_RE = re.compile(r"(?:^|[:,])METHOD=([A-Z0-9-]+)")
_KEY_IV_RE = re.compile(r"(?:^|,)IV=(0[xX][0-9A-Fa-f]+)")


@dataclass(frozen=True)
class _Segment:
    """One advertised HLS segment with its stable local identity."""

    generation: int
    url: str
    resource_id: str
    key_line: str
    duration: str
    discontinuity: bool = False


@dataclass
class _PlaylistState:
    """Track the live segment window and its media sequence."""

    segments: list[_Segment] = field(default_factory=list)
    sequence: int = 0
    last_new: float = 0.0
    generation: int = 0
    target_duration: int = 3
    next_id: int = 0
    known: set[tuple[int, str]] = field(default_factory=set)
    text: str = ""
    pending_discontinuity: bool = False
    timestamp_offset: int = 0
    next_dts: int | None = None
    rebased_generation: int = 0
    offsets: dict[int, int] = field(default_factory=dict)
    generation_next: dict[int, int] = field(default_factory=dict)


@dataclass(frozen=True)
class _SegmentMeta:
    """Decryption details kept in memory for one advertised segment."""

    generation: int
    key_url: str
    iv: bytes


@dataclass(frozen=True)
class _Allocation:
    """A cached signed playlist URL for one camera."""

    url: str
    created: float
    device_id: str
    coordinator: TuyaProjectCloudCoordinator
    generation: int


@dataclass(frozen=True)
class _Resource:
    """A signed segment or key URL reachable through the proxy."""

    url: str
    created: float
    content_type: str = "video/mp2t"
    body: bytes | None = None
    body_created: float | None = None


class TuyaStreamProxy:
    """Serve a stable local HLS endpoint backed by renewable Tuya URLs."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the proxy."""
        self.hass = hass
        self._routes: dict[str, tuple[str, TuyaProjectCloudCoordinator]] = {}
        self._allocations: dict[str, _Allocation] = {}
        self._resources: dict[str, _Resource] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._failures: dict[str, float] = {}
        self._playlist_state: dict[str, _PlaylistState] = {}
        self._generations: dict[str, int] = {}
        self._segment_meta: dict[str, _SegmentMeta] = {}
        self._rebase_locks: dict[str, asyncio.Lock] = {}
        self._base_url: str | None = None

    def register(self, device_id: str, coordinator: TuyaProjectCloudCoordinator) -> str:
        """Register a camera and return its opaque proxy token."""
        token = secrets.token_urlsafe(18)
        self._routes[token] = (device_id, coordinator)
        return token

    def _forget(self, token: str) -> None:
        """Remove every piece of state belonging to one proxy token."""
        self._routes.pop(token, None)
        self._allocations.pop(token, None)
        if (state := self._playlist_state.get(token)) is not None:
            state.last_new = 0.0
        self._locks.pop(token, None)
        self._failures.pop(token, None)
        self._playlist_state.pop(token, None)
        self._generations.pop(token, None)
        self._segment_meta = {
            key: value
            for key, value in self._segment_meta.items()
            if not key.startswith(f"{token}:segment:")
        }
        self._rebase_locks.pop(token, None)
        self._resources = {
            key: value
            for key, value in self._resources.items()
            if not key.startswith(f"{token}:")
        }

    def unregister(self, device_id: str) -> None:
        """Forget a camera when its platform is unloaded."""
        for token, route in list(self._routes.items()):
            if route[0] == device_id:
                self._forget(token)

    def unregister_coordinator(self, coordinator: TuyaProjectCloudCoordinator) -> None:
        """Forget all cameras of one config entry, including vanished devices."""
        for token, route in list(self._routes.items()):
            if route[1] is coordinator:
                self._forget(token)

    def invalidate(self, token: str) -> None:
        """Force the next playlist request to allocate a fresh Tuya URL.

        Segment and key resources stay available so a client that is still
        reading an older playlist does not receive 404s mid-playback.
        """
        self._allocations.pop(token, None)
        if (state := self._playlist_state.get(token)) is not None:
            state.last_new = 0.0

    def _base(self) -> str:
        """Return a stable base URL reachable from inside Home Assistant."""
        if self._base_url is None:
            try:
                base = get_url(
                    self.hass,
                    allow_external=False,
                    allow_cloud=False,
                    prefer_external=False,
                )
            except (NoURLAvailableError, TypeError, ValueError):
                base = None
            if isinstance(base, str) and base:
                self._base_url = base
            else:
                return FALLBACK_BASE_URL
        return self._base_url

    def source_url(self, token: str) -> str:
        """Return the local playlist URL exposed to HA and go2rtc."""
        return f"{self._base()}{PLAYLIST_PATH}/{token}/index.m3u8"

    def _resource_url(self, token: str, kind: str, resource_id: str) -> str:
        """Return an opaque URL with the extension HLS clients expect."""
        suffix = ".ts" if kind == "segment" else ".key"
        return f"{self._base()}{PLAYLIST_PATH}/{token}/{kind}/{resource_id}{suffix}"

    async def _allocation(
        self, token: str, *, force: bool = False
    ) -> _Allocation | None:
        """Return a cached allocation or allocate a fresh signed URL."""
        route = self._routes.get(token)
        if route is None:
            return None
        device_id, coordinator = route
        cached = self._allocations.get(token)
        if (
            not force
            and cached is not None
            and time.monotonic() - cached.created < ALLOCATION_TTL
        ):
            return cached
        failed = self._failures.get(token)
        if (
            failed is not None
            and time.monotonic() - failed < ALLOCATION_FAILURE_COOLDOWN
        ):
            return None
        lock = self._locks.setdefault(token, asyncio.Lock())
        async with lock:
            cached = self._allocations.get(token)
            if (
                not force
                and cached is not None
                and time.monotonic() - cached.created < ALLOCATION_TTL
            ):
                return cached
            try:
                url = await coordinator.client.async_allocate_stream(device_id, "hls")
            except TuyaApiError as err:
                self._failures[token] = time.monotonic()
                _LOGGER.debug(
                    "Cannot allocate a stream for camera %s (%s)",
                    redact_identifier(device_id),
                    type(err).__name__,
                )
                return None
            generation = self._generations.get(token, -1) + 1
            self._generations[token] = generation
            allocation = _Allocation(
                url, time.monotonic(), device_id, coordinator, generation
            )
            self._allocations[token] = allocation
            self._failures.pop(token, None)
            return allocation

    async def _fetch(self, url: str) -> tuple[bytes, dict[str, str]] | None:
        """Fetch an upstream resource without ever logging its URL."""
        try:
            async with async_get_clientsession(self.hass).get(
                url, timeout=FETCH_TIMEOUT
            ) as response:
                if response.status != 200:
                    return None
                return await response.read(), dict(response.headers)
        except (ClientError, OSError, TimeoutError):
            _LOGGER.debug("Cannot fetch an upstream HLS resource")
            return None

    def _store(self, token: str, kind: str, url: str, salt: str = "") -> str:
        """Store a signed URL under a stable, opaque identifier."""
        digest = hashlib.sha256(f"{token}:{salt}:{url}".encode()).hexdigest()[:20]
        content_type = "video/mp2t" if kind == "segment" else "application/octet-stream"
        self._resources[f"{token}:{kind}:{digest}"] = _Resource(
            url, time.monotonic(), content_type
        )
        return digest

    def _prune(self) -> None:
        """Drop expired allocations and resources."""
        now = time.monotonic()
        self._allocations = {
            token: allocation
            for token, allocation in self._allocations.items()
            if now - allocation.created < ALLOCATION_TTL
        }
        self._resources = {
            key: (
                replace(resource, body=None, body_created=None)
                if resource.body is not None
                and resource.body_created is not None
                and now - resource.body_created >= BODY_TTL
                else resource
            )
            for key, resource in self._resources.items()
            if now - resource.created < RESOURCE_TTL
        }
        valid_resources = set(self._resources)
        self._segment_meta = {
            key: meta
            for key, meta in self._segment_meta.items()
            if key in valid_resources
        }
        self._failures = {
            token: failed
            for token, failed in self._failures.items()
            if now - failed < ALLOCATION_FAILURE_COOLDOWN
        }

    async def playlist(self, token: str) -> str | None:
        """Return a local playlist with all signed upstream URLs hidden."""
        if token not in self._routes:
            return None
        state = self._playlist_state.setdefault(token, _PlaylistState())
        allocation = await self._allocation(token)
        if allocation is None:
            return None
        fetched = await self._fetch(allocation.url)
        forced = False
        if fetched is None:
            forced = True
            allocation = await self._allocation(token, force=True)
            if allocation is None:
                return None
            fetched = await self._fetch(allocation.url)
        if fetched is None:
            return None
        # A reachable but frozen playlist has no new segments. Renew before
        # FFmpeg consumes the remaining window and declares the stream ended.
        if (
            not forced
            and state.last_new
            and time.monotonic() - state.last_new > PLAYLIST_STALE_TIMEOUT
        ):
            allocation = await self._allocation(token, force=True)
            if allocation is None:
                return None
            refreshed = await self._fetch(allocation.url)
            if refreshed is None:
                return None
            fetched = refreshed
            state.last_new = time.monotonic()

        # A slower concurrent request must not rewind the window with its older
        # allocation. It gets the last valid playlist instead.
        if token not in self._routes or allocation.generation < state.generation:
            return state.text or None

        # Parse Tuya's media playlist into logical segments. Each segment keeps
        # the local URL it was first advertised with, even when a later renewal
        # replaces the signed upstream URL. That keeps FFmpeg's playlist cache
        # consistent and avoids reloading already-played segments.
        text = fetched[0].decode("utf-8", "replace")
        target_duration = 3
        key_line = ""
        upstream_key_url = ""
        key_method = ""
        key_iv = ""
        duration = "2"
        discontinuity = False
        candidates: list[tuple[str, str, str, bool]] = []
        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                continue
            if line.startswith("#EXT-X-TARGETDURATION:"):
                try:
                    target_duration = int(line.split(":", 1)[1])
                except ValueError:
                    target_duration = 3
            elif line.startswith("#EXT-X-KEY:"):

                def rewrite(match: re.Match[str]) -> str:
                    nonlocal upstream_key_url
                    upstream_key_url = urljoin(allocation.url, match.group(2))
                    # Stable per upstream key URL: an unchanged key must not
                    # get a new local URI on every playlist poll.
                    key_id = self._store(token, "key", upstream_key_url)
                    return (
                        f"{match.group(1)}"
                        f"{self._resource_url(token, 'key', key_id)}"
                        f"{match.group(3)}"
                    )

                key_line = _KEY_URI_RE.sub(rewrite, line)
                method = _KEY_METHOD_RE.search(line)
                key_method = method.group(1).upper() if method else ""
                iv = _KEY_IV_RE.search(line)
                key_iv = iv.group(1) if iv else ""
            elif line == "#EXT-X-DISCONTINUITY":
                discontinuity = True
            elif line.startswith("#EXTINF:"):
                duration = line.split(":", 1)[1].split(",", 1)[0] or "2"
            elif not line.startswith("#"):
                candidates.append(
                    (urljoin(allocation.url, line), duration, key_line, discontinuity)
                )
                duration = "2"
                discontinuity = False

        generation_changed = state.generation != allocation.generation
        if generation_changed:
            state.pending_discontinuity = True
        segment_iv: bytes | None = None
        if upstream_key_url and key_method in {"AES-128", "AES-128-CBC"} and key_iv:
            # HLS short IVs are left-padded with zeroes. Without an explicit
            # IV we must not guess one: the local window changes MEDIA-SEQUENCE.
            iv_hex = key_iv[2:].rjust(32, "0")
            try:
                segment_iv = bytes.fromhex(iv_hex)
            except ValueError:
                segment_iv = None
        fresh: list[tuple[tuple[int, str], _Segment]] = []
        for url, item_duration, item_key_line, item_discontinuity in candidates:
            identity = (allocation.generation, url)
            # Tuya keeps old segments in the growing list. Once a segment has
            # left our window it must not reappear as a "new" one later.
            if identity in state.known:
                continue
            state.next_id += 1
            resource_id = self._store(token, "segment", url, f"segment:{state.next_id}")
            if segment_iv is not None:
                self._segment_meta[f"{token}:segment:{resource_id}"] = _SegmentMeta(
                    allocation.generation, upstream_key_url, segment_iv
                )
            segment = _Segment(
                generation=allocation.generation,
                url=url,
                resource_id=resource_id,
                key_line=item_key_line,
                duration=item_duration,
                discontinuity=item_discontinuity,
            )
            fresh.append((identity, segment))

        # Mark the first segment of a new session even when the first playlist
        # of that session was still empty.
        if state.pending_discontinuity and fresh:
            identity, segment = fresh[0]
            fresh[0] = (identity, replace(segment, discontinuity=True))
            state.pending_discontinuity = False

        if generation_changed:
            # Keep already advertised segments at their original sequences and
            # introduce only one segment of the new session per refresh.
            keep_old = [
                item for item in state.segments if item.generation == state.generation
            ][-(PLAYLIST_WINDOW - 1) :]
            dropped = len(state.segments) - len(keep_old)
            selected = fresh[: max(0, PLAYLIST_WINDOW - len(keep_old))]
            state.sequence += dropped
            state.segments = keep_old + [segment for _, segment in selected]
            state.known = {
                identity
                for identity in state.known
                if identity[0] == allocation.generation
            }
            state.known.update(identity for identity, _ in selected)
        else:
            combined = state.segments + [segment for _, segment in fresh]
            dropped = max(0, len(combined) - PLAYLIST_WINDOW)
            state.sequence += dropped
            state.segments = combined[dropped:]
            state.known.update(identity for identity, _ in fresh)

        state.target_duration = target_duration
        state.generation = allocation.generation
        if fresh:
            state.last_new = time.monotonic()

        first_generation = (
            state.segments[0].generation if state.segments else state.generation
        )
        lines = [
            "#EXTM3U",
            "#EXT-X-VERSION:6",
            f"#EXT-X-TARGETDURATION:{state.target_duration}",
            f"#EXT-X-MEDIA-SEQUENCE:{state.sequence}",
            f"#EXT-X-DISCONTINUITY-SEQUENCE:{first_generation}",
        ]
        current_key = ""
        for segment in state.segments:
            if segment.key_line and segment.key_line != current_key:
                lines.append(segment.key_line)
                current_key = segment.key_line
            # The tag marks the allocation boundary for HLS clients. FFmpeg
            # does not shift timestamps for it, so the proxy rebases the
            # segment DTS values while serving the segment instead.
            if segment.discontinuity:
                lines.append("#EXT-X-DISCONTINUITY")
            lines.append(f"#EXTINF:{segment.duration},")
            lines.append(self._resource_url(token, "segment", segment.resource_id))
        self._prune()
        state.text = "\n".join(lines) + "\n"
        return state.text

    async def _rebase_segment(
        self, token: str, encrypted: bytes, meta: _SegmentMeta
    ) -> tuple[bytes, bool]:
        """Shift a segment onto the previous timeline; report if cacheable."""
        state = self._playlist_state.get(token)
        if state is None:
            return encrypted, False
        if (
            meta.generation < state.rebased_generation
            and meta.generation not in state.offsets
        ):
            return encrypted, False
        key_resource = await self._fetch(meta.key_url)
        if key_resource is None:
            _LOGGER.debug("Cannot fetch HLS key for timestamp rebasing")
            return encrypted, False
        key = key_resource[0]
        clear = decrypt(encrypted, key, meta.iv)
        if clear is None:
            _LOGGER.debug("Cannot decrypt HLS segment for timestamp rebasing")
            return encrypted, False
        first, last = timestamps(clear)
        if first is None or last is None:
            _LOGGER.debug("Cannot read HLS timestamps for rebasing")
            return encrypted, False
        lock = self._rebase_locks.setdefault(token, asyncio.Lock())
        async with lock:
            state = self._playlist_state.get(token)
            if state is None:
                return encrypted, False
            if (offset := state.offsets.get(meta.generation)) is None:
                if meta.generation < state.rebased_generation:
                    return encrypted, False
                offset = state.next_dts - first if state.next_dts is not None else 0
                state.offsets[meta.generation] = offset
            patched = shift(clear, offset)
            state.timestamp_offset = offset
            state.rebased_generation = max(meta.generation, state.rebased_generation)
            _, patched_last = timestamps(patched)
            if patched_last is not None:
                advanced = patched_last + FRAME_TICKS
                state.generation_next[meta.generation] = max(
                    state.generation_next.get(meta.generation, 0), advanced
                )
                state.next_dts = max(state.next_dts or 0, advanced)
        rewritten = encrypt(patched, key, meta.iv)
        if rewritten is None:
            return encrypted, False
        return rewritten, True

    async def resource(
        self, token: str, kind: str, resource_id: str
    ) -> tuple[bytes, dict[str, str]] | None:
        """Return a fetched segment or key by its opaque identifier."""
        cache_key = f"{token}:{kind}:{resource_id}"
        resource = self._resources.get(cache_key)
        now = time.monotonic()
        if resource is None or now - resource.created >= RESOURCE_TTL:
            return None
        if (
            resource.body is not None
            and resource.body_created is not None
            and now - resource.body_created < BODY_TTL
        ):
            return resource.body, {"Content-Type": resource.content_type}
        fetched = await self._fetch(resource.url)
        if fetched is None:
            return None
        body, headers = fetched
        cacheable = True
        # A real encrypted TS segment has many packets; tiny fixtures are left
        # untouched so the proxy keeps working with opaque test data.
        if (
            kind == "segment"
            and (meta := self._segment_meta.get(cache_key)) is not None
            and len(body) >= 188 * 2
        ):
            body, cacheable = await self._rebase_segment(token, body, meta)
        # A concurrent unload or invalidation must not resurrect old state.
        if token not in self._routes or cache_key not in self._resources:
            return None
        if cacheable:
            self._resources[cache_key] = replace(
                resource,
                body=body,
                body_created=time.monotonic(),
                content_type=headers.get("Content-Type", resource.content_type),
            )
        return body, headers


class _BaseView(HomeAssistantView):
    """Common behaviour for proxy views."""

    requires_auth = False

    def __init__(self, proxy: TuyaStreamProxy) -> None:
        """Store the proxy instance."""
        self.proxy = proxy

    @staticmethod
    def _missing() -> web.Response:
        """Return a response that reveals nothing about the upstream URL."""
        return web.Response(status=404, text="not found")


class TuyaPlaylistView(_BaseView):
    """Serve the stable local HLS playlist."""

    url = f"{PLAYLIST_PATH}/{{token}}/index.m3u8"
    name = "api:tuya_project_cloud:stream:playlist"

    async def get(self, request: web.Request, token: str) -> web.Response:
        """Return a rewritten playlist."""
        playlist = await self.proxy.playlist(token)
        if playlist is None:
            return self._missing()
        return web.Response(
            text=playlist,
            content_type="application/vnd.apple.mpegurl",
            headers={"Cache-Control": "no-store"},
        )


class TuyaSegmentView(_BaseView):
    """Serve rewritten media segments."""

    url = f"{PLAYLIST_PATH}/{{token}}/segment/{{resource_id}}"
    name = "api:tuya_project_cloud:stream:segment"

    async def get(
        self, request: web.Request, token: str, resource_id: str
    ) -> web.Response:
        """Return one media segment."""
        fetched = await self.proxy.resource(
            token, "segment", resource_id.removesuffix(".ts")
        )
        if fetched is None:
            return self._missing()
        body, headers = fetched
        return web.Response(
            body=body,
            content_type=headers.get("Content-Type", "video/mp2t"),
        )


class TuyaKeyView(_BaseView):
    """Serve rewritten HLS encryption keys."""

    url = f"{PLAYLIST_PATH}/{{token}}/key/{{resource_id}}"
    name = "api:tuya_project_cloud:stream:key"

    async def get(
        self, request: web.Request, token: str, resource_id: str
    ) -> web.Response:
        """Return one encryption key."""
        fetched = await self.proxy.resource(
            token, "key", resource_id.removesuffix(".key")
        )
        if fetched is None:
            return self._missing()
        body, headers = fetched
        return web.Response(
            body=body,
            content_type=headers.get("Content-Type", "application/octet-stream"),
        )


def async_register_stream_proxy(hass: HomeAssistant) -> TuyaStreamProxy:
    """Register the proxy views once and return the shared instance."""
    data = hass.data.setdefault(DOMAIN, {})
    if not isinstance(data, dict):
        data = {}
        hass.data[DOMAIN] = data
    proxy = data.get("stream_proxy")
    if not isinstance(proxy, TuyaStreamProxy):
        proxy = TuyaStreamProxy(hass)
        data["stream_proxy"] = proxy
        hass.http.register_view(TuyaPlaylistView(proxy))
        hass.http.register_view(TuyaSegmentView(proxy))
        hass.http.register_view(TuyaKeyView(proxy))
    return proxy
