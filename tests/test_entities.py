"""Tests for dynamic entity creation."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.components.climate import HVACMode
from homeassistant.const import EntityCategory

from custom_components.tuya_project_cloud.api import (
    TuyaDevice,
    TuyaFunction,
    TuyaShadowProperty,
)
from custom_components.tuya_project_cloud.climate import (
    async_setup_entry as climate_setup,
)
from custom_components.tuya_project_cloud.cover import async_setup_entry as cover_setup
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
        (sensor_setup, 3),
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
    """Sensor exposes the DPS value as diagnostic."""
    added = []
    await sensor_setup(MagicMock(), _entry(_device()), lambda e: added.extend(e))
    sensors = {entity.entity_description.key: entity for entity in added}
    assert sensors["battery"].native_value == 88
    assert sensors["battery"].entity_category is EntityCategory.DIAGNOSTIC


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
    assert entity.current_temperature == 20.0
    assert entity.target_temperature == 22.0


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
    assert sensors["voltage_l1"].native_value == 221.0
    assert sensors["current_l1"].native_value == 1.5
    assert sensors["power"].native_value == 10.0
    assert sensors["energy_total"].native_value == 2043.5
    assert sensors["firmware"].native_value == "2.9.3"
    assert sensors["charge_current"].native_value == 16.0
    assert sensors["heartbeat"].native_value is False
    assert all(entity.unique_id.startswith("dev2_shadow_") for entity in added)
