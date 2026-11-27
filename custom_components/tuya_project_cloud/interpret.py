"""Interpret verified Tuya integer DPS values.

Home Assistant's Tuya integration divides integer datapoints by ``10**scale``.
This module takes the scale from the device specification and keeps units and
classes fixed for the few codes verified in this project. The interpretation is
captured when the entity is set up so that metadata and values cannot drift
apart if specifications change later.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass

from .api import TuyaFunction
from .utils import coerce_float


@dataclass(frozen=True, slots=True)
class DpsSensorInterpretation:
    """Verified metadata for one interpreted DPS code."""

    translation_key: str
    device_class: SensorDeviceClass | None = None
    native_unit: str | None = None
    suggested_unit: str | None = None
    state_class: SensorStateClass | None = None
    precision: int | None = None


# These four codes are verified against Home Assistant Core's Tuya sensor
# definitions and the live product specifications in this project. Units and
# classes are fixed; only the scale comes from the device. Nothing else is
# guessed.
INTERPRETATIONS: dict[str, DpsSensorInterpretation] = {
    "cur_power": DpsSensorInterpretation(
        translation_key="dps_power_value",
        device_class=SensorDeviceClass.POWER,
        native_unit="W",
        state_class=SensorStateClass.MEASUREMENT,
        precision=1,
    ),
    "cur_voltage": DpsSensorInterpretation(
        translation_key="dps_voltage_value",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit="V",
        state_class=SensorStateClass.MEASUREMENT,
        precision=1,
    ),
    "cur_current": DpsSensorInterpretation(
        translation_key="dps_current_value",
        device_class=SensorDeviceClass.CURRENT,
        native_unit="mA",
        suggested_unit="A",
        state_class=SensorStateClass.MEASUREMENT,
        precision=1,
    ),
    "add_ele": DpsSensorInterpretation(
        translation_key="dps_energy_value",
        device_class=SensorDeviceClass.ENERGY,
        native_unit="kWh",
        suggested_unit="kWh",
        state_class=SensorStateClass.TOTAL_INCREASING,
        precision=3,
    ),
}


def _has_valid_scale(definition: TuyaFunction | None) -> bool:
    """Return whether the definition carries a usable integer scale."""
    if definition is None:
        return False
    scale = definition.values.get("scale")
    if isinstance(scale, bool):
        return False
    if isinstance(scale, str) and scale.strip().isdigit():
        scale = int(scale)
    return isinstance(scale, int) and 0 <= scale <= 6


def interpretation_for(
    code: str, definition: TuyaFunction | None
) -> DpsSensorInterpretation | None:
    """Return verified metadata only for an integer DP with a usable scale."""
    if definition is None:
        return None
    if definition.type.lower() != "integer":
        return None
    if not _has_valid_scale(definition):
        return None
    return INTERPRETATIONS.get(code)


def interpreted_value(
    value: Any,
    definition: TuyaFunction | None,
    interpretation: DpsSensorInterpretation | None,
) -> Any:
    """Apply the setup-time ``value / 10**scale`` decision to a new reading.

    The interpretation and definition are captured when the entity is created.
    Without both, the original value is returned unchanged. Out-of-range and
    non-numeric readings become ``None`` for integer datapoints, matching Home
    Assistant's Tuya type information.
    """
    if interpretation is None:
        return value
    if definition is None or definition.type.lower() != "integer":
        return value
    if value is None or isinstance(value, bool):
        return value

    number = coerce_float(value)
    if number is None:
        return None

    minimum = definition.values.get("min")
    maximum = definition.values.get("max")
    if (
        isinstance(minimum, (int, float))
        and not isinstance(minimum, bool)
        and number < minimum
    ):
        return None
    if (
        isinstance(maximum, (int, float))
        and not isinstance(maximum, bool)
        and number > maximum
    ):
        return None

    if not _has_valid_scale(definition):
        return value
    scale = definition.values.get("scale")
    if isinstance(scale, str):
        scale = int(scale)
    return round(number / (10**scale), 6)
