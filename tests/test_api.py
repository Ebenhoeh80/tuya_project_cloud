"""Tests for the Tuya OpenAPI client."""

from __future__ import annotations

import hashlib
import hmac
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.tuya_project_cloud.api import (
    TuyaApiError,
    TuyaAuthenticationError,
    TuyaAuthorizationError,
    TuyaConnectionError,
    TuyaOpenApi,
)


def _session() -> MagicMock:
    """Return a mocked aiohttp session."""
    return MagicMock()


def _client(session: MagicMock) -> TuyaOpenApi:
    """Return a client with deterministic credentials."""
    return TuyaOpenApi(session, "client", "secret", "eu")


def test_sign_matches_canonical_form() -> None:
    """The signature follows the documented canonical string."""
    client = _client(_session())
    signature = client._sign(
        "GET", "/v1.0/token?grant_type=1", "", "1000", "n", token=None
    )
    body_hash = hashlib.sha256(b"").hexdigest()
    material = f"client1000nGET\n{body_hash}\n\n/v1.0/token?grant_type=1"
    expected = (
        hmac.new(b"secret", material.encode(), hashlib.sha256).hexdigest().upper()
    )
    assert signature == expected


def test_sign_with_token_includes_token() -> None:
    """Business calls include the token in the signature material."""
    client = _client(_session())
    signature = client._sign("GET", "/path", "", "1000", "n", token="tok")
    body_hash = hashlib.sha256(b"").hexdigest()
    material = f"clienttok1000nGET\n{body_hash}\n\n/path"
    expected = (
        hmac.new(b"secret", material.encode(), hashlib.sha256).hexdigest().upper()
    )
    assert signature == expected


def test_unknown_region_raises() -> None:
    """An unknown region is rejected locally."""
    with pytest.raises(ValueError):
        TuyaOpenApi(_session(), "id", "secret", "mars")


@pytest.mark.asyncio
async def test_get_token_and_cache() -> None:
    """Token is fetched once and cached until expiry."""
    session = _session()
    client = _client(session)
    response = MagicMock()
    response.__aenter__ = AsyncMock(return_value=response)
    response.__aexit__ = AsyncMock(return_value=None)
    response.json = AsyncMock(
        return_value={
            "success": True,
            "result": {"access_token": "abc", "expire_time": 7200},
        }
    )
    session.request = MagicMock(return_value=response)
    await client.async_get_token()
    assert client._valid_token()
    assert client._access_token == "abc"


@pytest.mark.asyncio
async def test_get_token_error() -> None:
    """Missing token raises authentication error."""
    client = _client(_session())
    with (
        patch.object(client, "_request", AsyncMock(return_value={"success": True})),
        pytest.raises(TuyaAuthenticationError),
    ):
        await client.async_get_token()


@pytest.mark.asyncio
async def test_authorization_error() -> None:
    """Tuya errno 28841105 maps to TuyaAuthorizationError."""
    client = _client(_session())
    error = MagicMock()
    error.status = 200
    error.json = AsyncMock(
        return_value={"success": False, "code": 28841105, "msg": "not authorized"}
    )
    error.__aenter__ = AsyncMock(return_value=error)
    error.__aexit__ = AsyncMock(return_value=None)
    client._session = MagicMock()
    client._session.request = MagicMock(return_value=error)
    with pytest.raises(TuyaAuthorizationError):
        await client.async_get_devices()


@pytest.mark.asyncio
async def test_status_mapping() -> None:
    """Status list is mapped to code -> value."""
    client = _client(_session())
    with patch.object(
        client,
        "_request",
        AsyncMock(
            return_value={
                "result": [
                    {"code": "switch", "value": True},
                    {"code": "battery", "value": 88},
                ]
            }
        ),
    ):
        result = await client.async_get_status("dev1")
    assert result == {"switch": True, "battery": 88}


@pytest.mark.asyncio
async def test_functions_mapping() -> None:
    """Functions are read from result.functions."""
    client = _client(_session())
    with patch.object(
        client,
        "_request",
        AsyncMock(
            return_value={
                "result": {
                    "category": "cz",
                    "functions": [{"code": "switch", "type": "Boolean", "values": {}}],
                }
            }
        ),
    ):
        result = await client.async_get_functions("dev1")
    assert result["switch"].type == "Boolean"


@pytest.mark.asyncio
async def test_functions_normalize_string_values() -> None:
    """Tuya may return values as a JSON string instead of an object."""
    client = _client(_session())
    with patch.object(
        client,
        "_request",
        AsyncMock(
            return_value={
                "result": {
                    "functions": [
                        {
                            "code": "countdown_1",
                            "type": "Integer",
                            "values": '{"min":0,"max":86400,"step":1}',
                        },
                        {
                            "code": "wireless_lowpower",
                            "type": "Integer",
                            "values": "not json",
                        },
                    ]
                }
            }
        ),
    ):
        result = await client.async_get_functions("dev1")
    assert result["countdown_1"].values == {"min": 0, "max": 86400, "step": 1}
    assert result["wireless_lowpower"].values == {}


@pytest.mark.asyncio
async def test_send_command() -> None:
    """Commands are sent with correct payload."""
    client = _client(_session())
    request = AsyncMock(return_value={"success": True})
    with patch.object(client, "_request", request):
        await client.async_send_command("dev1", "switch", True)
    request.assert_awaited_once_with(
        "POST",
        "/v1.0/devices/dev1/commands",
        body={"commands": [{"code": "switch", "value": True}]},
    )


@pytest.mark.asyncio
async def test_generic_api_error() -> None:
    """Other errors map to the base API error."""
    client = _client(_session())
    response = MagicMock()
    response.status = 400
    response.json = AsyncMock(
        return_value={"success": False, "code": 1234, "msg": "bad"}
    )
    response.__aenter__ = AsyncMock(return_value=response)
    response.__aexit__ = AsyncMock(return_value=None)
    client._session = MagicMock()
    client._session.request = MagicMock(return_value=response)
    with pytest.raises(TuyaApiError):
        await client.async_get_devices()


@pytest.mark.asyncio
async def test_client_error_becomes_connection_error() -> None:
    """aiohttp client errors map to TuyaConnectionError."""
    from aiohttp import ClientError

    client = _client(_session())
    client._session = MagicMock()
    client._session.request = MagicMock(side_effect=ClientError("offline"))
    with pytest.raises(TuyaConnectionError):
        await client.async_get_devices()


@pytest.mark.asyncio
async def test_shadow_mapping() -> None:
    """Thing shadow properties are mapped by code."""
    client = _client(_session())
    request = AsyncMock(
        return_value={
            "result": {
                "properties": [
                    {"code": "x_work_state", "value": "300", "dp_id": 101, "time": 1},
                    {"code": "x_metrics", "value": "{}", "dp_id": 102, "time": 2},
                ]
            }
        }
    )
    with patch.object(client, "_request", request):
        result = await client.async_get_thing_shadow("dev1")
    request.assert_awaited_once_with("GET", "/v2.0/cloud/thing/dev1/shadow/properties")
    assert result["x_work_state"].value == "300"
    assert result["x_work_state"].dp_id == 101


@pytest.mark.asyncio
async def test_stream_allocation() -> None:
    """A short-lived URL is returned without being stored on the client."""
    client = _client(_session())
    request = AsyncMock(
        return_value={"result": {"url": "https://example.invalid/stream.m3u8"}}
    )
    with patch.object(client, "_request", request):
        url = await client.async_allocate_stream("dev1")
    request.assert_awaited_once_with(
        "POST",
        "/v1.0/devices/dev1/stream/actions/allocate",
        body={"type": "hls"},
    )
    assert url.endswith(".m3u8")
    assert not hasattr(client, "_stream_url")


@pytest.mark.asyncio
async def test_stream_allocation_without_url() -> None:
    """A response without a URL is reported as an API error."""
    client = _client(_session())
    with (
        patch.object(client, "_request", AsyncMock(return_value={"result": {}})),
        pytest.raises(TuyaApiError),
    ):
        await client.async_allocate_stream("dev1")
