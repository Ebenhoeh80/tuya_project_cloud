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
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import urljoin

from aiohttp import ClientError, ClientTimeout, web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.network import NoURLAvailableError, get_url

from .api import TuyaApiError
from .const import DOMAIN
from .utils import redact_identifier

if TYPE_CHECKING:
    from .coordinator import TuyaProjectCloudCoordinator

_LOGGER = logging.getLogger(__name__)

PLAYLIST_PATH = f"/api/{DOMAIN}/stream"
ALLOCATION_TTL = 120.0
RESOURCE_TTL = 600.0
ALLOCATION_FAILURE_COOLDOWN = 10.0
FETCH_TIMEOUT = ClientTimeout(total=15)
FALLBACK_BASE_URL = "http://localhost:8123"
_KEY_URI_RE = re.compile(r'(URI=")([^"]+)(")')


@dataclass(frozen=True)
class _Allocation:
    """A cached signed playlist URL for one camera."""

    url: str
    created: float
    device_id: str
    coordinator: TuyaProjectCloudCoordinator


@dataclass(frozen=True)
class _Resource:
    """A signed segment or key URL reachable through the proxy."""

    url: str
    created: float


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
        self._locks.pop(token, None)
        self._failures.pop(token, None)
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
            allocation = _Allocation(url, time.monotonic(), device_id, coordinator)
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

    def _store(self, token: str, kind: str, url: str) -> str:
        """Store a signed URL under an opaque identifier."""
        resource_id = hashlib.sha256(f"{token}:{url}".encode()).hexdigest()[:20]
        self._resources[f"{token}:{kind}:{resource_id}"] = _Resource(
            url, time.monotonic()
        )
        return resource_id

    def _prune(self) -> None:
        """Drop expired allocations and resources."""
        now = time.monotonic()
        self._allocations = {
            token: allocation
            for token, allocation in self._allocations.items()
            if now - allocation.created < ALLOCATION_TTL
        }
        self._resources = {
            key: resource
            for key, resource in self._resources.items()
            if now - resource.created < RESOURCE_TTL
        }
        self._failures = {
            token: failed
            for token, failed in self._failures.items()
            if now - failed < ALLOCATION_FAILURE_COOLDOWN
        }

    async def playlist(self, token: str) -> str | None:
        """Return a local playlist with all signed upstream URLs hidden."""
        allocation = await self._allocation(token)
        if allocation is None:
            return None
        fetched = await self._fetch(allocation.url)
        if fetched is None:
            allocation = await self._allocation(token, force=True)
            if allocation is None:
                return None
            fetched = await self._fetch(allocation.url)
        if fetched is None:
            return None
        text = fetched[0].decode("utf-8", "replace")
        # Tuya delivers a media playlist with relative .ts segments and an
        # AES-128 key URI. Master playlists and EXT-X-MAP are not expected.
        lines: list[str] = []
        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                continue
            if line.startswith("#EXT-X-KEY:"):

                def rewrite(match: re.Match[str]) -> str:
                    key_url = urljoin(allocation.url, match.group(2))
                    key_id = self._store(token, "key", key_url)
                    return (
                        f"{match.group(1)}"
                        f"{self._resource_url(token, 'key', key_id)}"
                        f"{match.group(3)}"
                    )

                line = _KEY_URI_RE.sub(rewrite, line)
            elif not line.startswith("#"):
                segment_url = urljoin(allocation.url, line)
                segment_id = self._store(token, "segment", segment_url)
                line = self._resource_url(token, "segment", segment_id)
            lines.append(line)
        self._prune()
        return "\n".join(lines) + "\n"

    async def resource(
        self, token: str, kind: str, resource_id: str
    ) -> tuple[bytes, dict[str, str]] | None:
        """Return a fetched segment or key by its opaque identifier."""
        resource = self._resources.get(f"{token}:{kind}:{resource_id}")
        if resource is None or time.monotonic() - resource.created >= RESOURCE_TTL:
            return None
        return await self._fetch(resource.url)


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
