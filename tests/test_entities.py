"""Tests for dynamic entity creation."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.components.climate import HVACMode
from homeassistant.const import EntityCategory
from homeassistant.helpers.typing import UNDEFINED

from custom_components.tuya_project_cloud import (
    camera,
    climate,
    cover,
    light,
    number,
    sensor,
    switch,
)
from custom_components.tuya_project_cloud.api import (
    TuyaDevice,
    TuyaFunction,
    TuyaShadowProperty,
)
from custom_components.tuya_project_cloud.climate import (
    async_setup_entry as climate_setup,
)
from custom_components.tuya_project_cloud.cover import async_setup_entry as cover_setup
from custom_components.tuya_project_cloud.entity import tuya_device_info
from custom_components.tuya_project_cloud.light import async_setup_entry as light_setup
from custom_components.tuya_project_cloud.number import (
    async_setup_entry as number_setup,
)
from custom_components.tuya_project_cloud.sensor import (
    async_setup_entry as sensor_setup,
)
from custom_components.tuya_project_cloud.switch import (
    async_setup_entry as switch_setup,
)


def _device() -> TuyaDevice:
    """Return a device with a broad DPS vocabulary."""
    return TuyaDevice(
        id="dev1",
        name="Test",
        category="cz",
        product_id="p1",
        online=True,
        status={
            "switch": True,
            "battery": 88,
            "temperature": 21,
            "bright_value": 50,
            "temp_set": 22,
            "temp_current": 20,
            "mode": "cool",
            "power": True,
            "percent_control": 40,
            "control": "open",
            "switch_led": True,
        },
        functions={
            "switch": TuyaFunction("switch", "Boolean"),
            "volume": TuyaFunction(
                "volume", "Integer", {"min": 0, "max": 10, "step": 1}
            ),
            "bright_value": TuyaFunction("bright_value", "Integer"),
            "temp_set": TuyaFunction("temp_set", "Integer"),
            "mode": TuyaFunction("mode", "Enum"),
            "control": TuyaFunction("control", "Enum"),
            "percent_control": TuyaFunction("percent_control", "Integer"),
        },
    )


def _entry(device: TuyaDevice) -> MagicMock:
    """Return a config entry with a coordinator holding one device."""
    coordinator = MagicMock()
    coordinator.data = {device.id: device}
    entry = MagicMock()
    entry.runtime_data = coordinator
    entry.options = {}
    entry.listeners = []

    def _listen(callback: object) -> MagicMock:
        entry.listeners.append(callback)
        return MagicMock()

    coordinator.async_add_listener.side_effect = _listen
    return entry


def _shadow_device() -> TuyaDevice:
    """Return a charger with a realistic IoT Core thing shadow."""
    return TuyaDevice(
        id="dev2",
        name="Charger",
        category="dj",
        product_id="p2",
        online=True,
        shadow={
            "x_work_state": TuyaShadowProperty("x_work_state", "300", 101, 1),
            "x_work_st_debug": TuyaShadowProperty("x_work_st_debug", "WORKING", 109, 1),
            "x_metrics": TuyaShadowProperty(
                "x_metrics",
                '{"L1":[2210,15,0],"L2":[2210,0,0],"L3":[2210,0,0],"p":100,"e":5}',
                102,
                1,
            ),
            "x_charge_current": TuyaShadowProperty("x_charge_current", "16", 150, 1),
            "x_charger_info": TuyaShadowProperty(
                "x_charger_info", '{"fv":"2.9.3","e":"20435","r":"Type B"}', 106, 1
            ),
            "x_heartbeat": TuyaShadowProperty("x_heartbeat", False, 153, 1),
        },
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("setup", "expected_count"),
    [
        (switch_setup, 1),
        (sensor_setup, 4),
        (number_setup, 1),
        (light_setup, 1),
        (climate_setup, 1),
        (cover_setup, 1),
    ],
)
async def test_platform_creation(setup, expected_count: int) -> None:
    """Each platform creates the expected number of entities."""
    added = []
    await setup(MagicMock(), _entry(_device()), lambda entities: added.extend(entities))
    assert len(added) == expected_count


@pytest.mark.asyncio
async def test_switch_state_and_command() -> None:
    """Switch reflects DPS and sends commands."""
    added = []
    await switch_setup(MagicMock(), _entry(_device()), lambda e: added.extend(e))
    entity = added[0]
    assert entity.is_on is True
    entity.coordinator.async_send_command = AsyncMock()
    await entity.async_turn_off()
    entity.coordinator.async_send_command.assert_called_once_with(
        "dev1", "switch", False
    )


@pytest.mark.asyncio
async def test_sensor_value_and_category() -> None:
    """Sensor exposes the DPS value with a readable name and verified metadata."""
    added = []
    await sensor_setup(MagicMock(), _entry(_device()), lambda e: added.extend(e))
    sensors = {entity.entity_description.key: entity for entity in added}
    battery = sensors["battery"]
    assert battery.native_value == 88
    assert battery.entity_category is EntityCategory.DIAGNOSTIC
    assert battery.entity_description.translation_key == "dps_battery"
    assert battery.device_class is None
    assert battery.native_unit_of_measurement is None
    assert sensors["temperature"].entity_description.translation_key == (
        "dps_temperature"
    )
    assert sensors["temperature"].native_unit_of_measurement is None


@pytest.mark.asyncio
async def test_number_value() -> None:
    """Number exposes range and value."""
    added = []
    await number_setup(MagicMock(), _entry(_device()), lambda e: added.extend(e))
    entity = added[0]
    assert entity.entity_description.key == "volume"
    assert entity.native_min_value == 0.0
    assert entity.native_max_value == 10.0


@pytest.mark.asyncio
async def test_number_skips_malformed_values() -> None:
    """Malformed Tuya function values must not break platform setup."""
    device = _device()
    device.functions["malformed"] = TuyaFunction("malformed", "Integer", "not json")
    device.functions["bad_range"] = TuyaFunction(
        "bad_range", "Integer", {"min": "x", "max": 10}
    )
    added = []
    await number_setup(MagicMock(), _entry(device), lambda e: added.extend(e))
    assert [entity.entity_description.key for entity in added] == ["volume"]


@pytest.mark.asyncio
async def test_light_brightness() -> None:
    """Light maps 0-100 DPS brightness to 0-255."""
    added = []
    await light_setup(MagicMock(), _entry(_device()), lambda e: added.extend(e))
    entity = added[0]
    assert entity.brightness == 128


@pytest.mark.asyncio
async def test_climate_modes() -> None:
    """Climate maps Tuya mode strings to HVAC modes."""
    added = []
    await climate_setup(MagicMock(), _entry(_device()), lambda e: added.extend(e))
    entity = added[0]
    assert entity.hvac_mode is HVACMode.COOL
    assert entity.native_current_temperature == 20.0
    assert entity.native_target_temperature == 22.0


@pytest.mark.asyncio
async def test_cover_position() -> None:
    """Cover exposes the DPS position."""
    added = []
    await cover_setup(MagicMock(), _entry(_device()), lambda e: added.extend(e))
    entity = added[0]
    assert entity.current_cover_position == 40


@pytest.mark.asyncio
async def test_shadow_sensors() -> None:
    """Shadow values are flattened, scaled and translated into sensors."""
    added = []
    await sensor_setup(MagicMock(), _entry(_shadow_device()), lambda e: added.extend(e))
    sensors = {
        entity.entity_description.key: entity
        for entity in added
        if entity.entity_description.key.startswith(
            (
                "work_",
                "voltage_",
                "current_",
                "charge_",
                "power",
                "energy_",
                "firmware",
                "heartbeat",
            )
        )
    }
    assert sensors["work_state_debug"].native_value == "WORKING"
    assert sensors["work_state_debug"].entity_category is EntityCategory.DIAGNOSTIC
    assert sensors["voltage_l1"].native_value == 221.0
    assert sensors["current_l1"].native_value == 1.5
    assert sensors["power"].native_value == 10.0
    assert sensors["energy_total"].native_value == 2043.5
    assert sensors["firmware"].native_value == "2.9.3"
    assert sensors["charge_current"].native_value == 16.0
    assert sensors["heartbeat"].native_value is False
    assert all(entity.unique_id.startswith("dev2_shadow_") for entity in added)


@pytest.mark.asyncio
async def test_number_invalid_value_and_setter() -> None:
    """Invalid number payloads do not raise and setter keeps integer DPS."""
    device = _device()
    device.status["volume"] = "abc"
    added = []
    await number_setup(MagicMock(), _entry(device), lambda e: added.extend(e))
    entity = added[0]
    assert entity.native_value is None
    entity.coordinator.async_send_command = AsyncMock()
    await entity.async_set_native_value(7.4)
    entity.coordinator.async_send_command.assert_called_once_with("dev1", "volume", 7)


@pytest.mark.asyncio
async def test_climate_invalid_values_and_setters() -> None:
    """Invalid climate payloads are ignored and commands stay integer-valued."""
    device = _device()
    device.status["temp_current"] = "abc"
    device.status["temp_set"] = "abc"
    added = []
    await climate_setup(MagicMock(), _entry(device), lambda e: added.extend(e))
    entity = added[0]
    assert entity.native_current_temperature is None
    assert entity.native_target_temperature is None
    entity.coordinator.async_send_command = AsyncMock()
    await entity.async_set_temperature(temperature=21.8)
    entity.coordinator.async_send_command.assert_called_once_with(
        "dev1", "temp_set", 21
    )


@pytest.mark.asyncio
async def test_cover_and_light_invalid_values() -> None:
    """Malformed DPS values leave cover and light state unknown, not broken."""
    device = _device()
    device.status["percent_control"] = "abc"
    device.status["bright_value"] = "abc"
    cover_added = []
    light_added = []
    await cover_setup(MagicMock(), _entry(device), lambda e: cover_added.extend(e))
    await light_setup(MagicMock(), _entry(device), lambda e: light_added.extend(e))
    assert cover_added[0].current_cover_position is None
    assert cover_added[0].is_closed is None
    assert light_added[0].brightness is None


@pytest.mark.asyncio
async def test_main_entities_do_not_duplicate_device_name() -> None:
    """Light, climate and cover rely on Home Assistant's device-name prefix."""
    device = _device()
    for setup in (light_setup, climate_setup, cover_setup):
        added = []
        await setup(MagicMock(), _entry(device), lambda e, a=added: a.extend(e))
        assert added[0].entity_description.name in (None, UNDEFINED)


@pytest.mark.asyncio
async def test_shadow_sensors_appear_when_shadow_arrives() -> None:
    """A charger that came online after startup gets its sensors dynamically."""
    device = TuyaDevice(
        id="dev2",
        name="Charger",
        category="dj",
        product_id="p2",
        online=True,
    )
    entry = _entry(device)
    added: list = []
    await sensor_setup(MagicMock(), entry, lambda e: added.extend(e))
    assert added == []
    device.shadow = {"x_work_state": TuyaShadowProperty("x_work_state", "300", 101, 1)}
    entry.listeners[0]()
    assert len(added) == 1
    assert added[0].unique_id == "dev2_shadow_work_state"
    entry.listeners[0]()
    assert len(added) == 1


@pytest.mark.asyncio
async def test_light_code_selection_is_stable() -> None:
    """Several matching DPS codes always resolve to the same priority code."""
    device = _device()
    device.status["light"] = True
    for _ in range(3):
        added: list = []
        await light_setup(MagicMock(), _entry(device), lambda e, a=added: a.extend(e))
        assert added[0].entity_description.key == "switch_led"


@pytest.mark.asyncio
async def test_switch_keeps_legacy_codes_and_excludes_light_codes() -> None:
    """Existing non-Boolean switches stay; only light duplicates are skipped."""
    device = _device()
    device.functions["switch_led"] = TuyaFunction("switch_led", "Boolean")
    device.functions["pir_switch"] = TuyaFunction("pir_switch", "Enum")
    added: list = []
    await switch_setup(MagicMock(), _entry(device), lambda e: added.extend(e))
    keys = {entity.entity_description.key for entity in added}
    assert "switch" in keys
    assert "pir_switch" in keys
    assert "switch_led" not in keys


@pytest.mark.asyncio
async def test_shadow_sensors_available_without_legacy_status() -> None:
    """Shadow sensors follow the shadow, not the unsupported legacy status."""
    device = _shadow_device()
    device.last_update_success = False
    added: list = []
    await sensor_setup(MagicMock(), _entry(device), lambda e: added.extend(e))
    assert added
    assert all(entity.available for entity in added)


@pytest.mark.asyncio
async def test_shadow_sensors_unavailable_without_fresh_shadow() -> None:
    """Shadow sensors need fresh shadow data and an online device."""
    device = _shadow_device()
    added: list = []
    await sensor_setup(MagicMock(), _entry(device), lambda e: added.extend(e))
    assert added
    entity = added[0]
    assert entity.available is True

    device.shadow = {}
    assert entity.available is False

    device.shadow = _shadow_device().shadow
    device.shadow_last_update_success = False
    assert entity.available is False

    device.shadow_last_update_success = True
    device.online = False
    assert entity.available is False


@pytest.mark.asyncio
async def test_stale_device_is_unavailable() -> None:
    """A failed status read marks DPS entities unavailable."""
    device = _device()
    device.last_update_success = False
    added: list = []
    await switch_setup(MagicMock(), _entry(device), lambda e: added.extend(e))
    assert added[0].available is False


def test_shadow_value_edge_cases() -> None:
    """Malformed shadow payloads return None instead of crashing."""
    from custom_components.tuya_project_cloud.shadow import (
        ShadowSensorDescription,
        shadow_value,
    )

    description = ShadowSensorDescription(
        key="voltage_l1",
        translation_key="voltage_l1",
        code="x_metrics",
        json_path=("L1", 0),
        device_class="voltage",
    )
    assert (
        shadow_value(
            {"x_metrics": TuyaShadowProperty("x_metrics", "{broken", 1, 1)},
            description,
        )
        is None
    )
    assert (
        shadow_value(
            {"x_metrics": TuyaShadowProperty("x_metrics", '{"L1":[]}', 1, 1)},
            description,
        )
        is None
    )
    assert (
        shadow_value(
            {"x_metrics": TuyaShadowProperty("x_metrics", '{"L1":["hot"]}', 1, 1)},
            description,
        )
        is None
    )
    assert shadow_value({}, description) is None


@pytest.mark.asyncio
async def test_dps_entities_use_readable_translation_keys() -> None:
    """Known and unknown DPS codes get localized names without changing IDs."""
    device = _device()
    device.status["humidity_value"] = 55
    device.status["status_unknown"] = 1
    device.functions["child_lock"] = TuyaFunction("child_lock", "Boolean")
    device.functions["mystery_switch"] = TuyaFunction("mystery_switch", "Boolean")
    device.functions["bright_value_v2"] = TuyaFunction(
        "bright_value_v2", "Integer", {"min": 0, "max": 100, "step": 1}
    )
    device.status["bright_value_v2"] = 50

    sensors: list = []
    switches: list = []
    numbers: list = []
    await sensor_setup(MagicMock(), _entry(device), lambda e: sensors.extend(e))
    await switch_setup(MagicMock(), _entry(device), lambda e: switches.extend(e))
    await number_setup(MagicMock(), _entry(device), lambda e: numbers.extend(e))

    sensor_by_code = {entity.entity_description.key: entity for entity in sensors}
    switch_by_code = {entity.entity_description.key: entity for entity in switches}
    number_by_code = {entity.entity_description.key: entity for entity in numbers}

    assert sensor_by_code["humidity_value"].entity_description.translation_key == (
        "dps_humidity"
    )
    assert sensor_by_code["status_unknown"].entity_description.translation_key == (
        "dps_unknown_sensor"
    )
    assert sensor_by_code[
        "status_unknown"
    ].entity_description.translation_placeholders == {"code": "status_unknown"}
    assert switch_by_code["child_lock"].entity_category is None
    assert switch_by_code["mystery_switch"].entity_description.translation_key == (
        "dps_unknown_switch"
    )
    assert number_by_code["volume"].entity_description.translation_key == "dps_volume"
    # The light uses bright_value, so the v2 DPS must stay available as a number.
    assert "bright_value_v2" in number_by_code
    assert "bright_value" not in number_by_code
    assert {entity.unique_id for entity in sensors} >= {
        "dev1_humidity_value",
        "dev1_status_unknown",
    }
    assert {entity.unique_id for entity in switches} >= {
        "dev1_child_lock",
        "dev1_mystery_switch",
    }
    assert "dev1_volume" in {entity.unique_id for entity in numbers}


def test_device_info_contains_firmware_from_shadow() -> None:
    """Device registry shows a readable firmware value when the shadow has one."""
    device = _device()
    device.shadow["x_charger_info"] = TuyaShadowProperty(
        "x_charger_info", {"fv": "1.2.3"}
    )
    info = tuya_device_info(device)
    assert info["sw_version"] == "1.2.3"
    assert info["name"] == "Test"
    assert info["model"] == "p1"


def test_device_info_without_firmware_has_no_placeholder() -> None:
    """Missing firmware is not shown as an internal code or blank value."""
    info = tuya_device_info(_device())
    assert "sw_version" not in info


@pytest.mark.asyncio
async def test_brightness_v2_number_remains_without_light_entity() -> None:
    """A brightness number is not lost when the device has no light entity."""
    device = _device()
    for code in ("switch_led", "led_switch", "light", "switch_light"):
        device.functions.pop(code, None)
        device.status.pop(code, None)
    device.functions["bright_value_v2"] = TuyaFunction(
        "bright_value_v2", "Integer", {"min": 0, "max": 100, "step": 1}
    )
    device.status["bright_value_v2"] = 50

    numbers: list = []
    await number_setup(MagicMock(), _entry(device), lambda e: numbers.extend(e))
    by_code = {entity.entity_description.key: entity for entity in numbers}
    assert "bright_value_v2" in by_code
    assert "bright_value" not in by_code


@pytest.mark.asyncio
async def test_brightness_v2_number_is_skipped_when_light_uses_it() -> None:
    """The v2 brightness is not duplicated when a light exposes the same DPS."""
    device = _device()
    device.functions.pop("bright_value", None)
    device.status.pop("bright_value", None)
    device.functions["bright_value_v2"] = TuyaFunction(
        "bright_value_v2", "Integer", {"min": 0, "max": 100, "step": 1}
    )
    device.status["bright_value_v2"] = 50

    numbers: list = []
    await number_setup(MagicMock(), _entry(device), lambda e: numbers.extend(e))
    assert "bright_value_v2" not in {
        entity.entity_description.key for entity in numbers
    }


@pytest.mark.asyncio
async def test_number_keeps_translation_and_placeholders_after_range() -> None:
    """Injecting the numeric range does not drop the localized metadata."""
    device = _device()
    device.functions["mystery_number"] = TuyaFunction(
        "mystery_number", "Integer", {"min": 0, "max": 9, "step": 1}
    )
    device.status["mystery_number"] = 3
    numbers: list = []
    await number_setup(MagicMock(), _entry(device), lambda e: numbers.extend(e))
    by_code = {entity.entity_description.key: entity for entity in numbers}
    description = by_code["mystery_number"].entity_description
    assert description.translation_key == "dps_unknown_number"
    assert description.translation_placeholders == {"code": "mystery_number"}
    assert description.native_min_value == 0
    assert description.native_max_value == 9
    assert description.native_step == 1


@pytest.mark.asyncio
async def test_unknown_switch_uses_code_only_as_placeholder() -> None:
    """The internal DPS code is available for diagnosis, not a hard-coded name."""
    device = _device()
    device.functions["mystery_switch"] = TuyaFunction("mystery_switch", "Boolean")
    switches: list = []
    await switch_setup(MagicMock(), _entry(device), lambda e: switches.extend(e))
    by_code = {entity.entity_description.key: entity for entity in switches}
    description = by_code["mystery_switch"].entity_description
    assert description.translation_key == "dps_unknown_switch"
    assert description.translation_placeholders == {"code": "mystery_switch"}
    assert description.name is UNDEFINED


def test_all_platforms_declare_parallel_updates() -> None:
    """Cloud platforms avoid unbounded concurrent writes to one coordinator."""
    for module in (camera, climate, cover, light, number, sensor, switch):
        assert hasattr(module, "PARALLEL_UPDATES"), module.__name__
        assert isinstance(module.PARALLEL_UPDATES, int)
