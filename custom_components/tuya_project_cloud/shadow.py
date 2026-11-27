"""Mapping of IoT Core thing shadow properties to Home Assistant sensors.

Only codes that were observed in a live shadow response are mapped. Values whose
scaling or unit could not be verified are deliberately left out.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfPower,
)

if TYPE_CHECKING:
    from .api import TuyaDevice, TuyaShadowProperty


@dataclass(frozen=True, kw_only=True)
class ShadowSensorDescription(SensorEntityDescription):
    """Describe one sensor derived from a shadow property."""

    code: str
    json_path: tuple[str | int, ...] = ()
    scale: float = 1.0


CHARGER_SHADOW_SENSORS: tuple[ShadowSensorDescription, ...] = (
    ShadowSensorDescription(
        key="work_state",
        translation_key="work_state",
        code="x_work_state",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    ShadowSensorDescription(
        key="work_state_debug",
        translation_key="work_state_debug",
        code="x_work_st_debug",
    ),
    ShadowSensorDescription(
        key="voltage_l1",
        translation_key="voltage_l1",
        code="x_metrics",
        json_path=("L1", 0),
        scale=0.1,
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    ShadowSensorDescription(
        key="voltage_l2",
        translation_key="voltage_l2",
        code="x_metrics",
        json_path=("L2", 0),
        scale=0.1,
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    ShadowSensorDescription(
        key="voltage_l3",
        translation_key="voltage_l3",
        code="x_metrics",
        json_path=("L3", 0),
        scale=0.1,
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    ShadowSensorDescription(
        key="current_l1",
        translation_key="current_l1",
        code="x_metrics",
        json_path=("L1", 1),
        scale=0.1,
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    ShadowSensorDescription(
        key="current_l2",
        translation_key="current_l2",
        code="x_metrics",
        json_path=("L2", 1),
        scale=0.1,
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    ShadowSensorDescription(
        key="current_l3",
        translation_key="current_l3",
        code="x_metrics",
        json_path=("L3", 1),
        scale=0.1,
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    ShadowSensorDescription(
        key="power",
        translation_key="power",
        code="x_metrics",
        json_path=("p",),
        scale=0.1,
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    ShadowSensorDescription(
        key="energy_session",
        translation_key="energy_session",
        code="x_metrics",
        json_path=("e",),
        scale=0.1,
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=1,
    ),
    ShadowSensorDescription(
        key="charge_current",
        translation_key="charge_current",
        code="x_charge_current",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
    ),
    ShadowSensorDescription(
        key="max_current_cfg",
        translation_key="max_current_cfg",
        code="x_max_current_cfg",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
    ),
    ShadowSensorDescription(
        key="energy_total",
        translation_key="energy_total",
        code="x_charger_info",
        json_path=("e",),
        scale=0.1,
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=1,
    ),
    ShadowSensorDescription(
        key="firmware",
        translation_key="firmware",
        code="x_charger_info",
        json_path=("fv",),
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    ShadowSensorDescription(
        key="rcd_type",
        translation_key="rcd_type",
        code="x_charger_info",
        json_path=("r",),
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    ShadowSensorDescription(
        key="heartbeat",
        translation_key="heartbeat",
        code="x_heartbeat",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


def has_shadow_sensors(device: TuyaDevice) -> bool:
    """Return True when at least one mapped shadow code is present."""
    return any(
        description.code in device.shadow for description in CHARGER_SHADOW_SENSORS
    )


def shadow_value(
    shadow: dict[str, TuyaShadowProperty], description: ShadowSensorDescription
) -> Any:
    """Extract, scale and normalize the value for one shadow sensor."""
    prop = shadow.get(description.code)
    if prop is None:
        return None
    value = prop.value if hasattr(prop, "value") else prop.get("value")
    # Tuya returns structured shadow properties as JSON strings.
    if isinstance(value, str) and value[:1] in ("{", "["):
        try:
            value = json.loads(value)
        except ValueError:
            return None
    for part in description.json_path:
        if isinstance(value, dict):
            value = value.get(str(part))
        elif isinstance(value, (list, tuple)) and isinstance(part, int):
            if part >= len(value):
                return None
            value = value[part]
        else:
            return None
        if value is None:
            return None
    if description.device_class is not None and isinstance(value, str):
        try:
            value = float(value)
        except ValueError:
            return None
    if description.scale != 1.0:
        try:
            return round(float(value) * description.scale, 3)
        except (TypeError, ValueError):
            return None
    return value
