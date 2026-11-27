"""Async client for the Tuya OpenAPI using a cloud project token only."""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from aiohttp import ClientError, ClientSession, ClientTimeout

from .const import (
    ENDPOINT_ASSOCIATED_DEVICES,
    ENDPOINT_DEVICE_COMMANDS,
    ENDPOINT_DEVICE_FUNCTIONS,
    ENDPOINT_DEVICE_SPECIFICATIONS,
    ENDPOINT_DEVICE_STATUS,
    ENDPOINT_STREAM_ALLOCATE,
    ENDPOINT_THING_SHADOW,
    ENDPOINT_TOKEN,
    ERR_API_NOT_AUTHORIZED,
    ERR_NO_PERMISSION,
    ERR_SIGN_INVALID,
    REGIONS,
)

_LOGGER = logging.getLogger(__name__)

EMPTY_BODY_HASH = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


class TuyaApiError(Exception):
    """Base exception for Tuya OpenAPI errors."""


class TuyaAuthenticationError(TuyaApiError):
    """Invalid credentials, signature or token."""


class TuyaAuthorizationError(TuyaApiError):
    """The project is not authorized for the requested API or command."""

    def __init__(self, message: str, *, code: int | None = None) -> None:
        """Initialize the error with an optional Tuya errno."""
        super().__init__(message)
        self.code = code


class TuyaConnectionError(TuyaApiError):
    """Transient network or server error."""


@dataclass(slots=True)
class TuyaFunction:
    """A single DPS function or status definition."""

    code: str
    type: str = ""
    values: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TuyaShadowProperty:
    """A single property from the IoT Core thing shadow."""

    code: str
    value: Any = None
    dp_id: int | None = None
    time: int | None = None


@dataclass(slots=True)
class TuyaDevice:
    """A cloud device visible to the project."""

    id: str
    name: str
    category: str
    product_id: str
    online: bool
    uid: str = ""
    owner_id: str = ""
    status: dict[str, Any] = field(default_factory=dict)
    functions: dict[str, TuyaFunction] = field(default_factory=dict)
    specifications: dict[str, TuyaFunction] = field(default_factory=dict)
    shadow: dict[str, TuyaShadowProperty] = field(default_factory=dict)


class TuyaOpenApi:
    """Minimal async Tuya OpenAPI client with HMAC-SHA256 signing."""

    def __init__(
        self,
        session: ClientSession,
        access_id: str,
        access_secret: str,
        region: str,
    ) -> None:
        """Initialize the client. Credentials stay in memory only."""
        if region not in REGIONS:
            raise ValueError(f"Unknown region: {region}")
        self._session = session
        self._access_id = access_id
        self._secret = access_secret.encode("utf-8")
        self._base_url = REGIONS[region].rstrip("/")
        self._access_token: str | None = None
        self._expires_at = 0.0

    def _sign(
        self,
        method: str,
        path: str,
        body: str,
        timestamp: str,
        nonce: str,
        *,
        token: str | None = None,
    ) -> str:
        """Build the canonical HMAC-SHA256 signature."""
        body_hash = (
            EMPTY_BODY_HASH
            if not body
            else hashlib.sha256(body.encode("utf-8")).hexdigest()
        )
        string_to_sign = f"{method}\n{body_hash}\n\n{path}"
        material = (
            f"{self._access_id}{token}{timestamp}{nonce}{string_to_sign}"
            if token
            else f"{self._access_id}{timestamp}{nonce}{string_to_sign}"
        )
        return (
            hmac.new(self._secret, material.encode("utf-8"), hashlib.sha256)
            .hexdigest()
            .upper()
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        authenticated: bool = True,
    ) -> dict[str, Any]:
        """Perform a signed request and return the decoded response."""
        if authenticated and not self._valid_token():
            await self.async_get_token()

        payload = "" if body is None else _json_dumps(body)
        timestamp = str(int(time.time() * 1000))
        nonce = _nonce()
        token = self._access_token if authenticated else None
        signature = self._sign(method, path, payload, timestamp, nonce, token=token)
        headers = {
            "client_id": self._access_id,
            "sign": signature,
            "sign_method": "HMAC-SHA256",
            "t": timestamp,
            "nonce": nonce,
        }
        if token:
            headers["access_token"] = token
        if body is not None:
            headers["Content-Type"] = "application/json"

        try:
            async with self._session.request(
                method,
                f"{self._base_url}{path}",
                headers=headers,
                data=payload if body is not None else None,
                timeout=ClientTimeout(total=20),
            ) as response:
                data = await response.json(content_type=None)
        except (ClientError, TimeoutError, OSError) as err:
            raise TuyaConnectionError("Cannot reach Tuya OpenAPI") from err
        except ValueError as err:
            raise TuyaApiError("Invalid JSON from Tuya OpenAPI") from err

        if not isinstance(data, dict):
            raise TuyaApiError("Unexpected response from Tuya OpenAPI")

        if data.get("success") is False:
            code = data.get("code")
            message = str(data.get("msg", "Tuya API error"))
            if code == ERR_API_NOT_AUTHORIZED:
                raise TuyaAuthorizationError(message, code=code)
            if code == ERR_NO_PERMISSION:
                raise TuyaAuthorizationError(message, code=code)
            if ERR_SIGN_INVALID in message.lower() or code in (1004, 1005):
                raise TuyaAuthenticationError(message)
            if response.status in (401, 403):
                raise TuyaAuthenticationError(message)
            raise TuyaApiError(message)

        return data

    def _valid_token(self) -> bool:
        """Return True when a token is present and not close to expiry."""
        return bool(self._access_token) and time.time() < self._expires_at - 60

    async def async_get_token(self) -> None:
        """Fetch a project token using grant_type=1 (no app user login)."""
        data = await self._request(
            "GET", f"{ENDPOINT_TOKEN}?grant_type=1", authenticated=False
        )
        result = data.get("result", data)
        token = result.get("access_token")
        if not token:
            raise TuyaAuthenticationError("Tuya token response missing access_token")
        self._access_token = token
        self._expires_at = time.time() + int(result.get("expire_time", 7200))

    async def async_get_devices(self) -> list[dict[str, Any]]:
        """Return devices linked to the project's app accounts."""
        data = await self._request("GET", f"{ENDPOINT_ASSOCIATED_DEVICES}?size=100")
        result = data.get("result", {})
        devices = result.get("devices", [])
        return [device for device in devices if isinstance(device, dict)]

    async def async_get_status(self, device_id: str) -> dict[str, Any]:
        """Return the current DPS status as code -> value."""
        path = ENDPOINT_DEVICE_STATUS.format(device_id=device_id)
        data = await self._request("GET", path)
        result = data.get("result", [])
        return {
            item["code"]: item.get("value")
            for item in result
            if isinstance(item, dict) and "code" in item
        }

    async def async_get_functions(self, device_id: str) -> dict[str, TuyaFunction]:
        """Return writable function codes for a device."""
        path = ENDPOINT_DEVICE_FUNCTIONS.format(device_id=device_id)
        data = await self._request("GET", path)
        result = data.get("result", {})
        functions = result.get("functions", [])
        return {
            item["code"]: TuyaFunction(
                code=item["code"],
                type=item.get("type", ""),
                values=item.get("values", {}),
            )
            for item in functions
            if isinstance(item, dict) and "code" in item
        }

    async def async_get_specifications(self, device_id: str) -> dict[str, TuyaFunction]:
        """Return the full DPS specification for a device."""
        path = ENDPOINT_DEVICE_SPECIFICATIONS.format(device_id=device_id)
        data = await self._request("GET", path)
        result = data.get("result", {})
        definitions = {}
        for key in ("functions", "status"):
            for item in result.get(key, []):
                if isinstance(item, dict) and "code" in item:
                    definitions[item["code"]] = TuyaFunction(
                        code=item["code"],
                        type=item.get("type", ""),
                        values=item.get("values", {}),
                    )
        return definitions

    async def async_send_command(self, device_id: str, code: str, value: Any) -> None:
        """Send a single DPS command to a device."""
        path = ENDPOINT_DEVICE_COMMANDS.format(device_id=device_id)
        await self._request(
            "POST", path, body={"commands": [{"code": code, "value": value}]}
        )

    async def async_get_thing_shadow(
        self, device_id: str
    ) -> dict[str, TuyaShadowProperty]:
        """Return IoT Core thing shadow properties as code -> property."""
        path = ENDPOINT_THING_SHADOW.format(device_id=device_id)
        data = await self._request("GET", path)
        result = data.get("result", {})
        properties = result.get("properties", [])
        return {
            item["code"]: TuyaShadowProperty(
                code=item["code"],
                value=item.get("value"),
                dp_id=item.get("dp_id"),
                time=item.get("time"),
            )
            for item in properties
            if isinstance(item, dict) and "code" in item
        }

    async def async_allocate_stream(
        self, device_id: str, stream_type: str = "hls"
    ) -> str:
        """Allocate a short-lived signed stream URL without storing it."""
        path = ENDPOINT_STREAM_ALLOCATE.format(device_id=device_id)
        data = await self._request("POST", path, body={"type": stream_type})
        result = data.get("result", {})
        url = result.get("url") if isinstance(result, dict) else None
        if not url:
            raise TuyaApiError("Tuya stream allocation returned no URL")
        return str(url)

    async def async_validate(self) -> None:
        """Validate credentials by fetching a token and the device list."""
        await self.async_get_token()
        await self.async_get_devices()


def _nonce() -> str:
    """Return a random nonce without importing uuid at module scope."""
    import uuid

    return uuid.uuid4().hex


def _json_dumps(value: dict[str, Any]) -> str:
    """Serialize JSON compactly without external dependencies."""
    import json

    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)
