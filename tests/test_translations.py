"""Regression tests for complete and consistent DE/EN translations."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from custom_components.tuya_project_cloud import diagnostics, dps
from custom_components.tuya_project_cloud.interpret import INTERPRETATIONS
from custom_components.tuya_project_cloud.shadow import CHARGER_SHADOW_SENSORS

COMPONENT = (
    Path(__file__).resolve().parents[1] / "custom_components" / "tuya_project_cloud"
)


def _load(name: str) -> dict[str, Any]:
    """Load one translation resource."""
    path = (
        COMPONENT / "strings.json"
        if name == "strings"
        else COMPONENT / "translations" / f"{name}.json"
    )
    return json.loads(path.read_text(encoding="utf-8"))


def _leaves(data: dict[str, Any], prefix: str = "") -> dict[str, str]:
    """Flatten a translation tree into leaf keys and values."""
    result: dict[str, str] = {}
    for key, value in data.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            result.update(_leaves(value, path))
        else:
            result[path] = str(value)
    return result


def _placeholders(value: str) -> set[str]:
    """Return the placeholders used in a translation string."""
    return set(re.findall(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}", value))


def test_strings_and_english_are_identical() -> None:
    """Hassfest requires strings.json and en.json to match exactly."""
    assert _load("strings") == _load("en")


def test_translation_keys_are_complete() -> None:
    """DE and EN contain the same non-empty keys with matching placeholders."""
    base = _leaves(_load("strings"))
    german = _leaves(_load("de"))
    english = _leaves(_load("en"))

    assert set(base) == set(german) == set(english)
    assert all(value.strip() for value in base.values())
    for key, value in base.items():
        assert _placeholders(value) == _placeholders(german[key]), key
        assert _placeholders(value) == _placeholders(english[key]), key


def test_every_entity_key_is_translated() -> None:
    """Every translation_key used by the integration resolves to a name."""
    strings = _load("strings")["entity"]
    used = {
        ("sensor", description.translation_key)
        for description in CHARGER_SHADOW_SENSORS
    }
    used.update(
        ("sensor", description.translation_key)
        for description in dps.SENSOR_DESCRIPTIONS.values()
    )
    used.update(
        ("sensor", interpretation.translation_key)
        for interpretation in INTERPRETATIONS.values()
    )
    used.update(
        ("switch", description.translation_key)
        for description in dps.SWITCH_DESCRIPTIONS.values()
    )
    used.update(
        ("number", description.translation_key)
        for description in dps.NUMBER_DESCRIPTIONS.values()
    )
    for platform in ("sensor", "switch", "number"):
        used.add((platform, f"dps_unknown_{platform}"))
    for platform, key in used:
        assert key in strings[platform], (platform, key)
        assert "name" in strings[platform][key], (platform, key)


def test_charger_states_are_translated() -> None:
    """Raw charger states shown in the UI have DE and EN labels."""
    for language in ("strings", "de", "en"):
        sensor = _load(language)["entity"]["sensor"]
        assert set(sensor["work_state"]["state"]) >= {"101", "300"}
        assert set(sensor["work_state_debug"]["state"]) >= {"sleep", "working"}
    assert _load("de")["entity"]["sensor"]["work_state"]["state"]["100"] == "Offline"


def test_all_state_keys_are_hassfest_compatible() -> None:
    """Hassfest rejects translation keys that are not snake_case."""
    for language in ("strings", "de", "en"):
        for platform, entries in _load(language)["entity"].items():
            for key, entry in entries.items():
                for state_key in entry.get("state", {}):
                    assert state_key == state_key.lower(), (
                        language,
                        platform,
                        key,
                        state_key,
                    )


def test_user_facing_errors_are_translated() -> None:
    """Errors and repairs use localized sentences instead of raw API text."""
    for language in ("strings", "de", "en"):
        data = _load(language)
        assert set(data["exceptions"]) >= {
            "authentication_failed",
            "setup_failed",
            "update_failed",
            "command_failed",
            "command_not_authorized",
        }
        assert set(data["issues"]) >= {
            "api_not_authorized",
            "iot_core_not_authorized",
            "command_not_authorized",
            "region_mismatch",
        }
        for key, value in data["exceptions"].items():
            assert value["message"].strip(), (language, key)
        for key, value in data["issues"].items():
            assert value["title"].strip(), (language, key)
            assert value["description"].strip(), (language, key)


def _visible_keys(platform: str) -> set[str]:
    """Return every translation key that can become a friendly name."""
    descriptions = {
        "sensor": list(dps.SENSOR_DESCRIPTIONS.values())
        + list(CHARGER_SHADOW_SENSORS)
        + list(INTERPRETATIONS.values()),
        "switch": list(dps.SWITCH_DESCRIPTIONS.values()),
        "number": list(dps.NUMBER_DESCRIPTIONS.values()),
    }[platform]
    keys = {item.translation_key for item in descriptions}
    keys.add(f"dps_unknown_{platform}")
    return keys


def test_visible_entity_names_are_unique() -> None:
    """No device shows two entities with exactly the same friendly name."""
    for language in ("strings", "de", "en"):
        entities = _load(language)["entity"]
        for platform in ("sensor", "switch", "number"):
            names = [entities[platform][key]["name"] for key in _visible_keys(platform)]
            assert len(names) == len(set(names)), (language, platform)


def test_unknown_dps_codes_are_labelled_as_codes() -> None:
    """A raw DPS code is never shown as a bare friendly name."""
    for language in ("strings", "de", "en"):
        entities = _load(language)["entity"]
        for platform in ("sensor", "switch", "number"):
            name = entities[platform][f"dps_unknown_{platform}"]["name"]
            assert "code:" in name.lower(), (language, platform, name)


def test_safety_and_function_names_are_unambiguous() -> None:
    """Destructive switches and camera filters say what they really do."""
    de = _load("de")["entity"]
    en = _load("en")["entity"]
    assert "löscht alle daten" in de["switch"]["dps_sd_format"]["name"].lower()
    assert "erases all data" in en["switch"]["dps_sd_format"]["name"].lower()
    assert "nur" in de["switch"]["dps_human_filter"]["name"].lower()
    assert "only" in en["switch"]["dps_human_filter"]["name"].lower()
    assert (
        de["sensor"]["dps_energy_value"]["name"] != de["sensor"]["energy_total"]["name"]
    )
    assert (
        en["sensor"]["dps_energy_value"]["name"] != en["sensor"]["energy_total"]["name"]
    )


def test_diagnostics_redaction_label_is_plain_language() -> None:
    """The diagnostics hint avoids developer jargon such as hash prefixes."""
    source = (COMPONENT / "diagnostics.py").read_text(encoding="utf-8")
    assert diagnostics._redact is not None
    assert "pseudonymized device ID" in source
    assert "sha256-prefix" not in source
