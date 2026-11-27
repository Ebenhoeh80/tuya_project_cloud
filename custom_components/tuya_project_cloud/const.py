"""Constants for the Tuya Project Cloud integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "tuya_project_cloud"

CONF_ACCESS_ID = "access_id"
CONF_ACCESS_SECRET = "access_secret"
CONF_REGION = "region"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_ENABLE_CAMERA = "enable_camera"
CONF_ENABLE_SHADOW = "enable_shadow"

DEFAULT_SCAN_INTERVAL = timedelta(seconds=30)
DEFAULT_ENABLE_CAMERA = True
DEFAULT_ENABLE_SHADOW = True

# Thing shadow data changes while charging; refresh it slower than DPS status.
SHADOW_REFRESH_INTERVAL = 60

# Ordered tuples keep unique IDs stable across restarts when a device exposes
# more than one compatible DPS code.
LIGHT_CODES: tuple[str, ...] = ("switch_led", "led_switch", "light", "switch_light")
CONTROL_CODES: tuple[str, ...] = ("control", "control_2", "switch")

REGIONS = {
    "cn": "https://openapi.tuyacn.com",
    "us": "https://openapi.tuyaus.com",
    "us_east": "https://openapi-ueaz.tuyaus.com",
    "eu": "https://openapi.tuyaeu.com",
    "eu_west": "https://openapi-weaz.tuyaeu.com",
    "in": "https://openapi.tuyain.com",
    "sg": "https://openapi-sg.iotbing.com",
}

# Verified working endpoint families (live 2026-11-27).
ENDPOINT_TOKEN = "/v1.0/token"
ENDPOINT_ASSOCIATED_DEVICES = "/v1.0/iot-01/associated-users/devices"
ENDPOINT_DEVICE_STATUS = "/v1.0/devices/{device_id}/status"
ENDPOINT_DEVICE_FUNCTIONS = "/v1.0/devices/{device_id}/functions"
ENDPOINT_DEVICE_SPECIFICATIONS = "/v1.0/devices/{device_id}/specifications"
ENDPOINT_DEVICE_COMMANDS = "/v1.0/devices/{device_id}/commands"
ENDPOINT_THING_SHADOW = "/v2.0/cloud/thing/{device_id}/shadow/properties"
ENDPOINT_STREAM_ALLOCATE = "/v1.0/devices/{device_id}/stream/actions/allocate"

PLATFORMS = (
    "switch",
    "sensor",
    "number",
    "light",
    "climate",
    "cover",
    "camera",
)

# Error codes observed or documented.
ERR_SIGN_INVALID = "sign invalid"
ERR_NO_PERMISSION = 1106
ERR_API_NOT_AUTHORIZED = 28841105

ISSUE_AUTH_FAILED = "auth_failed"
ISSUE_API_NOT_AUTHORIZED = "api_not_authorized"
ISSUE_COMMAND_NOT_AUTHORIZED = "command_not_authorized"
ISSUE_IOT_CORE_NOT_AUTHORIZED = "iot_core_not_authorized"
ISSUE_REGION_MISMATCH = "region_mismatch"
