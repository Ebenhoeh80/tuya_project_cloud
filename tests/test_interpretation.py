"""Tests for specification-driven interpretation of Tuya DPS values."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import EntityCategory

from custom_components.tuya_project_cloud.api import TuyaDevice, TuyaFunction
from custom_components.tuya_project_cloud.interpret import (
    INTERPRETATIONS,
    interpretation_for,
    interpreted_value,
)
from custom_components.tuya_project_cloud.sensor import async_setup_entry


def _spec(code: str, **values: object) -> TuyaFunction:
    """Return an integer specification for a DPS code."""
    return TuyaFunction(code, "Integer", values)


def _interpreted(raw: object, code: str, definition: TuyaFunction | None) -> object:
    """Apply the interpretation that setup would have captured."""
    return interpreted_value(raw, definition, interpretation_for(code, definition))


def _device() -> TuyaDevice:
    """Return a device with the live Balkonkraftwerk specification subset."""
    return TuyaDevice(
        id="dev1",
        name="Test",
        category="cz",
        product_id="p1",
        online=True,
        status={"cur_power": 0, "cur_voltage": 2187, "cur_current": 0, "add_ele": 1},
        specifications={
            "cur_power": _spec(
                "cur_power", min=0, max=80000, scale=1, step=1, unit="W"
            ),
            "cur_voltage": _spec(
                "cur_voltage", min=0, max=5000, scale=1, step=1, unit="V"
            ),
            "cur_current": _spec(
                "cur_current", min=0, max=30000, scale=0, step=1, unit="mA"
            ),
            "add_ele": _spec("add_ele", min=0, max=50000, scale=3, step=100),
        },
    )


def _entry(device: TuyaDevice) -> MagicMock:
    """Return a config entry with a coordinator holding one device."""
    coordinator = MagicMock()
    coordinator.data = {device.id: device}
    entry = MagicMock()
    entry.runtime_data = coordinator
    entry.async_on_unload = MagicMock()
    coordinator.async_add_listener.return_value = MagicMock()
    return entry


@pytest.mark.parametrize(
    ("code", "raw", "definition", "expected"),
    [
        ("cur_power", 37, _spec("cur_power", scale=1), 3.7),
        ("cur_voltage", 2187, _spec("cur_voltage", scale=1), 218.7),
        ("cur_current", 5000, _spec("cur_current", scale=0), 5000.0),
        ("add_ele", 1, _spec("add_ele", scale=3), 0.001),
        ("cur_power", "37", _spec("cur_power", scale=1), 3.7),
        ("cur_power", 37, TuyaFunction("cur_power", "Enum"), 37),
        ("cur_power", 37, _spec("cur_power", scale="1"), 3.7),
        ("cur_power", 37, _spec("cur_power", scale="bad"), 37),
        ("power_coe", 13422, _spec("power_coe", scale=0), 13422),
        ("cur_power", True, _spec("cur_power", scale=1), True),
        ("cur_power", None, _spec("cur_power", scale=1), None),
        ("cur_power", "abc", _spec("cur_power", scale=1), None),
        ("cur_power", 90000, _spec("cur_power", min=0, max=80000, scale=1), None),
        ("cur_power", 37, None, 37),
    ],
)
def test_interpreted_value(
    code: str, raw: object, definition, expected: object
) -> None:
    """Scale only integer values with a usable specification."""
    assert _interpreted(raw, code, definition) == expected


def test_interpretation_requires_integer_definition() -> None:
    """A known code without an integer specification stays a raw sensor."""
    assert interpretation_for("cur_power", _spec("cur_power", scale=1)) is not None
    assert interpretation_for("cur_power", TuyaFunction("cur_power", "Enum")) is None
    assert interpretation_for("cur_power", None) is None
    assert interpretation_for("unknown", _spec("unknown", scale=1)) is None


@pytest.mark.asyncio
async def test_interpreted_sensors_match_native_tuya() -> None:
    """Sensors use the verified units, classes and readable names."""
    added: list = []
    await async_setup_entry(MagicMock(), _entry(_device()), lambda e: added.extend(e))
    sensors = {entity.entity_description.key: entity for entity in added}

    assert len(sensors) == 4
    power = sensors["cur_power"]
    assert power.native_value == 0.0
    assert power.device_class is SensorDeviceClass.POWER
    assert power.native_unit_of_measurement == "W"
    assert power.state_class is SensorStateClass.MEASUREMENT
    assert power.entity_description.translation_key == "dps_power_value"
    assert power.suggested_display_precision == 1
    assert power.unique_id == "dev1_cur_power"

    voltage = sensors["cur_voltage"]
    assert voltage.native_value == 218.7
    assert voltage.device_class is SensorDeviceClass.VOLTAGE
    assert voltage.native_unit_of_measurement == "V"
    assert voltage.suggested_display_precision == 1

    current = sensors["cur_current"]
    assert current.native_value == 0.0
    assert current.device_class is SensorDeviceClass.CURRENT
    assert current.native_unit_of_measurement == "mA"
    assert current.suggested_unit_of_measurement == "A"
    assert current.suggested_display_precision == 1

    energy = sensors["add_ele"]
    assert energy.native_value == 0.001
    assert energy.device_class is SensorDeviceClass.ENERGY
    assert energy.native_unit_of_measurement == "kWh"
    assert energy.state_class is SensorStateClass.TOTAL_INCREASING
    assert energy.entity_description.translation_key == "dps_energy_value"
    assert energy.suggested_display_precision == 3
    assert energy.unique_id == "dev1_add_ele"


@pytest.mark.asyncio
async def test_interpretation_is_captured_at_setup() -> None:
    """Later specification changes cannot desynchronize metadata and values."""
    device = TuyaDevice(
        id="dev3",
        name="Late spec",
        category="cz",
        product_id="p3",
        online=True,
        status={"cur_power": 37},
    )
    added: list = []
    await async_setup_entry(MagicMock(), _entry(device), lambda e: added.extend(e))
    sensor = added[0]
    assert sensor.native_value == 37
    assert sensor.device_class is None
    assert sensor.native_unit_of_measurement is None

    device.specifications["cur_power"] = _spec("cur_power", scale=1)
    assert sensor.native_value == 37
    assert sensor.device_class is None

    scaled_device = _device()
    scaled_device.status = {"cur_power": 37}
    scaled_added: list = []
    await async_setup_entry(
        MagicMock(), _entry(scaled_device), lambda e: scaled_added.extend(e)
    )
    scaled_sensor = scaled_added[0]
    assert scaled_sensor.native_value == 3.7
    scaled_device.specifications["cur_power"] = _spec("cur_power", scale=2)
    assert scaled_sensor.native_value == 3.7


@pytest.mark.asyncio
@pytest.mark.parametrize("scale", [None, "bad", -1, 7, True])
async def test_invalid_scale_keeps_raw_metadata(scale: object) -> None:
    """A known code with an unusable scale never claims interpreted units."""
    values = {} if scale is None else {"scale": scale}
    device = TuyaDevice(
        id="dev4",
        name="Bad scale",
        category="cz",
        product_id="p4",
        online=True,
        status={"cur_power": 37},
        specifications={"cur_power": _spec("cur_power", **values)},
    )
    added: list = []
    await async_setup_entry(MagicMock(), _entry(device), lambda e: added.extend(e))
    sensor = added[0]
    assert sensor.native_value == 37
    assert sensor.device_class is None
    assert sensor.native_unit_of_measurement is None
    assert sensor.entity_description.translation_key == "dps_power"


@pytest.mark.asyncio
async def test_unknown_and_calibration_codes_stay_raw() -> None:
    """Codes without a verified interpretation keep the raw diagnostic shape."""
    device = _device()
    device.status = {"power_coe": 13422, "unknown_power": 7}
    added: list = []
    await async_setup_entry(MagicMock(), _entry(device), lambda e: added.extend(e))
    sensors = {entity.entity_description.key: entity for entity in added}

    calibration = sensors["power_coe"]
    assert calibration.native_value == 13422
    assert isinstance(calibration.native_value, int)
    assert calibration.device_class is None
    assert calibration.native_unit_of_measurement is None
    assert calibration.entity_category is EntityCategory.DIAGNOSTIC
    assert calibration.entity_description.translation_key == "dps_power_calibration"

    unknown = sensors["unknown_power"]
    assert unknown.native_value == 7
    assert unknown.entity_description.translation_key == "dps_unknown_sensor"


def test_all_interpretations_have_translation_keys() -> None:
    """Every interpretation points at a translated, non-raw entity name."""
    component = (
        Path(__file__).resolve().parents[1]
        / "custom_components"
        / ("tuya_project_cloud")
    )
    resources = {
        name: json.loads(
            (
                component
                / ("strings.json" if name == "strings" else f"translations/{name}.json")
            ).read_text(encoding="utf-8")
        )["entity"]["sensor"]
        for name in ("strings", "de", "en")
    }
    for interpretation in INTERPRETATIONS.values():
        key = interpretation.translation_key
        assert key.startswith("dps_")
        for name, sensors in resources.items():
            assert key in sensors, (name, key)
            assert sensors[key]["name"].strip(), (name, key)
            assert "raw value" not in sensors[key]["name"].lower(), (name, key)
            assert "Rohwert" not in sensors[key]["name"], (name, key)
