"""Tests for shared helpers."""

from __future__ import annotations

from custom_components.tuya_project_cloud.utils import (
    coerce_float,
    coerce_int,
    redact_identifier,
    redact_value,
)


def test_redact_identifier_is_stable_and_irreversible() -> None:
    """Device IDs never appear verbatim in logs or diagnostics."""
    label = redact_identifier("dev-secret-123")
    assert label == redact_identifier("dev-secret-123")
    assert label != redact_identifier("dev-secret-124")
    assert "dev-secret-123" not in label
    assert len(label) == 12


def test_redact_value_is_case_insensitive_and_handles_tuples() -> None:
    """Nested sensitive keys are redacted regardless of case."""
    result = redact_value(
        {
            "AccessToken": "x",
            "items": ({"M3U8": "y"}, "ok"),
            "note": "see https://example.invalid/live.m3u8",
        }
    )
    assert result == {
        "AccessToken": "**REDACTED**",
        "items": [{"M3U8": "**REDACTED**"}, "ok"],
        "note": "**REDACTED**",
    }


def test_coerce_helpers_tolerate_unexpected_dps_values() -> None:
    """Malformed Tuya payloads return None instead of raising."""
    assert coerce_float("12.5") == 12.5
    assert coerce_float("nope") is None
    assert coerce_float(True) is None
    assert coerce_int("7") == 7
    assert coerce_int("nope") is None
