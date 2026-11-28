"""User-facing metadata for Tuya DPS codes.

The codes come from the cloud API and are internal identifiers. They are mapped
to readable, localized entity names here. Verified integer measurement codes
are additionally interpreted in :mod:`interpret.py`; all other values stay raw.
"""

from __future__ import annotations

from homeassistant.components.number import NumberEntityDescription
from homeassistant.components.sensor import SensorEntityDescription
from homeassistant.components.switch import SwitchEntityDescription
from homeassistant.const import EntityCategory

SENSOR_DESCRIPTIONS: dict[str, SensorEntityDescription] = {
    code: SensorEntityDescription(
        key=code,
        translation_key=translation_key,
        entity_category=EntityCategory.DIAGNOSTIC,
    )
    for code, translation_key in (
        ("battery", "dps_battery"),
        ("humidity", "dps_humidity"),
        ("humidity_value", "dps_humidity_2"),
        ("pm25", "dps_pm25"),
        ("pm25_value", "dps_pm25_2"),
        ("pm10", "dps_pm10"),
        ("co2", "dps_co2"),
        ("co2_value", "dps_co2_2"),
        ("temperature", "dps_temperature"),
        ("va_temperature", "dps_temperature_2"),
        ("temp_current", "dps_temperature_3"),
        ("cur_power", "dps_power"),
        ("power_coe", "dps_power_calibration"),
        ("add_ele", "dps_energy_2"),
        ("energy", "dps_energy"),
        ("voltage", "dps_voltage"),
        ("cur_voltage", "dps_voltage_2"),
        ("current", "dps_current"),
        ("cur_current", "dps_current_2"),
        ("signal", "dps_signal"),
        ("status", "dps_status"),
        ("sd_status", "dps_sd_status"),
        ("wireless_powermode", "dps_power_mode"),
    )
}

# No EntityCategory is assigned deliberately: moving existing switches into
# HA's "Configuration" section would change dashboards and Assist exposure.
SWITCH_DESCRIPTIONS: dict[str, SwitchEntityDescription] = {
    code: SwitchEntityDescription(key=code, translation_key=translation_key)
    for code, translation_key in (
        ("switch", "dps_switch"),
        ("switch_1", "dps_switch_1"),
        ("onoff", "dps_onoff"),
        ("enable", "dps_enable"),
        ("overcharge_switch", "dps_overcharge"),
        ("child_lock", "dps_child_lock"),
        ("switch_inching", "dps_inching"),
        ("basic_indicator", "dps_indicator"),
        ("basic_flip", "dps_flip"),
        ("basic_osd", "dps_osd"),
        ("basic_private", "dps_privacy"),
        ("sd_format", "dps_sd_format"),
        ("motion_record", "dps_motion_record"),
        ("record_switch", "dps_record"),
        ("wireless_lowpower", "dps_power_saving"),
        ("wireless_awake", "dps_wake"),
        ("pir_switch", "dps_motion_sensor"),
        ("doorbell_active", "dps_doorbell"),
        ("motion_switch", "dps_motion_detection"),
        ("motion_tracking", "dps_motion_tracking"),
        ("humanoid_filter", "dps_human_filter"),
        ("cruise_switch", "dps_cruise"),
        ("ptz_stop", "dps_ptz_stop"),
        ("ptz_calibration", "dps_ptz_calibration"),
    )
}

NUMBER_DESCRIPTIONS: dict[str, NumberEntityDescription] = {
    code: NumberEntityDescription(key=code, translation_key=translation_key)
    for code, translation_key in (
        ("countdown_1", "dps_countdown_1"),
        ("basic_device_volume", "dps_volume"),
        ("volume", "dps_volume"),
        ("wireless_lowpower", "dps_power_saving_value"),
    )
}
