"""Base entity for Tuya Project Cloud."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import TuyaDevice
from .const import DOMAIN, TUYA_DEVICE_DOMAIN
from .coordinator import TuyaProjectCloudCoordinator
from .shadow import ShadowSensorDescription, shadow_firmware, shadow_value


def tuya_device_info(device: TuyaDevice) -> DeviceInfo:
    """Build stable device metadata, adding firmware when the shadow has it."""
    info = DeviceInfo(
        identifiers={
            (DOMAIN, device.id),
            (TUYA_DEVICE_DOMAIN, device.id),
        },
        name=device.name,
        manufacturer="Tuya",
        model=device.product_id,
    )
    if firmware := shadow_firmware(device):
        info["sw_version"] = firmware
    return info


class TuyaProjectCloudEntity(CoordinatorEntity[TuyaProjectCloudCoordinator]):
    """Base class for entities backed by a Tuya DPS code."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: TuyaProjectCloudCoordinator,
        device: TuyaDevice,
        description: EntityDescription,
        dps_code: str,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self.entity_description = description
        self._device_id = device.id
        self._dps_code = dps_code
        self._attr_unique_id = f"{device.id}_{dps_code}"
        self._attr_device_info = tuya_device_info(device)

    @property
    def _tuya_device(self) -> TuyaDevice | None:
        """Return the current device data."""
        return (
            self.coordinator.data.get(self._device_id)
            if self.coordinator.data
            else None
        )

    @property
    def available(self) -> bool:
        """Return availability based on device online state."""
        device = self._tuya_device
        return super().available and bool(
            device and device.online and device.last_update_success
        )

    @property
    def dps_value(self) -> Any:
        """Return the raw DPS value for this entity."""
        device = self._tuya_device
        return device.status.get(self._dps_code) if device else None

    async def _async_send(self, value: Any) -> None:
        """Send a DPS command for this entity."""
        await self.coordinator.async_send_command(
            self._device_id, self._dps_code, value
        )


class TuyaShadowEntity(CoordinatorEntity[TuyaProjectCloudCoordinator]):
    """Base class for entities backed by an IoT Core thing shadow property."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: TuyaProjectCloudCoordinator,
        device: TuyaDevice,
        description: ShadowSensorDescription,
    ) -> None:
        """Initialize the entity with a shadow-prefixed unique ID."""
        super().__init__(coordinator)
        self.entity_description = description
        self._device_id = device.id
        self._attr_unique_id = f"{device.id}_shadow_{description.key}"
        self._attr_device_info = tuya_device_info(device)

    @property
    def _tuya_device(self) -> TuyaDevice | None:
        """Return the current device data."""
        return (
            self.coordinator.data.get(self._device_id)
            if self.coordinator.data
            else None
        )

    @property
    def available(self) -> bool:
        """Return availability from a successfully refreshed IoT Core shadow."""
        device = self._tuya_device
        return super().available and bool(
            device
            and device.online
            and device.shadow
            and device.shadow_last_update_success
        )

    @property
    def shadow_sensor_value(self) -> Any:
        """Return the scaled value for this shadow sensor."""
        device = self._tuya_device
        return shadow_value(device.shadow, self.entity_description) if device else None
