"""Small shared helpers for the Tuya Project Cloud integration."""

from __future__ import annotations

import hashlib
import re
from typing import Any

# Fragments are checked after removing separators and case, so variants such as
# "AccessToken", "M3U8" or "hls_url_signed" are redacted as well.
SENSITIVE_FRAGMENTS = (
    "token",
    "secret",
    "credential",
    "password",
    "signature",
    "stream",
    "url",
    "m3u8",
    "localkey",
    "ownerid",
    "uid",
)
_URL_PATTERN = re.compile(r"https?://\S+", re.IGNORECASE)


def redact_identifier(value: Any) -> str:
    """Return a stable pseudonym for an ID used in logs or diagnostics.

    The original Tuya device ID is never exposed. The prefix is stable enough to
    correlate repeated messages for the same device without printing the ID.
    """
    text = "" if value is None else str(value)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _is_sensitive_key(key: Any) -> bool:
    """Return True when a diagnostics key may carry a secret or a stream URL."""
    normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
    return any(fragment in normalized for fragment in SENSITIVE_FRAGMENTS)


def redact_value(value: Any) -> Any:
    """Recursively redact secrets and URLs from diagnostics payloads."""
    if isinstance(value, dict):
        return {
            key: "**REDACTED**" if _is_sensitive_key(key) else redact_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact_value(item) for item in value]
    if isinstance(value, str) and _URL_PATTERN.search(value):
        return "**REDACTED**"
    return value


def coerce_float(value: Any) -> float | None:
    """Convert a DPS value to float without raising on unexpected Tuya data."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def coerce_int(value: Any) -> int | None:
    """Convert a DPS value to int without raising on unexpected Tuya data."""
    number = coerce_float(value)
    return int(number) if number is not None else None
