"""Diagnostics support for Tuya Project Cloud."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntry

from .const import (
    CONF_ENABLE_CAMERA,
    CONF_ENABLE_SHADOW,
    CONF_REGION,
    CONF_SCAN_INTERVAL,
)

SENSITIVE_KEYS = {
    "access_id",
    "access_token",
    "refresh_token",
    "access_secret",
    "client_secret",
    "secret",
    "token",
    "stream_url",
    "signed_url",
    "url",
    "m3u8",
    "local_key",
    "uid",
    "owner_id",
    "lat",
    "lon",
    "ip",
}


def _redact(value: Any) -> Any:
    """Recursively redact sensitive data."""
    if isinstance(value, dict):
        return {
            key: "**REDACTED**" if key.lower() in SENSITIVE_KEYS else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    return value


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return redacted diagnostics for a config entry."""
    coordinator = entry.runtime_data
    devices = coordinator.data or {}
    return _redact(
        {
            "region": entry.data.get(CONF_REGION),
            "access_id": "**REDACTED**",
            "access_secret": "**REDACTED**",
            "scan_interval": entry.options.get(CONF_SCAN_INTERVAL),
            "enable_shadow": entry.options.get(CONF_ENABLE_SHADOW),
            "enable_camera": entry.options.get(CONF_ENABLE_CAMERA),
            "last_update_success": coordinator.last_update_success,
            "api_not_authorized": coordinator.api_not_authorized,
            "iot_core_not_authorized": getattr(
                coordinator, "iot_core_not_authorized", False
            ),
            "device_count": len(devices),
            "devices": [
                {
                    "id": device.id,
                    "category": device.category,
                    "product_id": device.product_id,
                    "online": device.online,
                    "status_codes": sorted(device.status),
                    "function_codes": sorted(device.functions),
                    "shadow_codes": sorted(device.shadow),
                }
                for device in devices.values()
            ],
        }
    )


async def async_get_device_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry, device: DeviceEntry
) -> dict[str, Any]:
    """Return redacted diagnostics for a single device."""
    coordinator = entry.runtime_data
    device_id = next(
        (
            identifier[1]
            for identifier in device.identifiers
            if identifier[0] == "tuya_project_cloud"
        ),
        None,
    )
    tuya_device = (coordinator.data or {}).get(device_id) if device_id else None
    return _redact(
        {
            "device_id": device_id,
            "category": tuya_device.category if tuya_device else None,
            "status": tuya_device.status if tuya_device else {},
            "functions": {
                code: {"type": func.type, "values": func.values}
                for code, func in tuya_device.functions.items()
            }
            if tuya_device
            else {},
            "shadow_codes": sorted(tuya_device.shadow) if tuya_device else [],
        }
    )
