"""Sensor platform for Senzomatic integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import SenzomaticDataUpdateCoordinator
from .const import (
    DOMAIN,
    SENSOR_ABS_HUMIDITY,
    SENSOR_MOISTURE,
    SENSOR_REL_HUMIDITY,
    SENSOR_TEMPERATURE,
    UNIT_GRAMS_PER_M3,
)

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensor platform."""
    coordinator: SenzomaticDataUpdateCoordinator = hass.data[DOMAIN][
        config_entry.entry_id
    ]

    entities: list[SenzomaticSensor] = []

    # Wait for first data fetch
    if coordinator.data and "devices" in coordinator.data:
        for device in coordinator.data["devices"]:
            device_id = device["id"]
            device_name = device["name"]
            device_model = device["model"]

            # Check which sensors have data for this device
            sensor_data = coordinator.data.get("sensors", {}).get(device_id, {})

            # Temperature sensor
            if SENSOR_TEMPERATURE in sensor_data:
                entities.append(
                    SenzomaticSensor(
                        coordinator=coordinator,
                        device_id=device_id,
                        device_name=device_name,
                        device_model=device_model,
                        sensor_type=SENSOR_TEMPERATURE,
                        name="Temperature",
                        unit=UnitOfTemperature.CELSIUS,
                        device_class=SensorDeviceClass.TEMPERATURE,
                        state_class=SensorStateClass.MEASUREMENT,
                    )
                )

            # Relative humidity sensor
            if SENSOR_REL_HUMIDITY in sensor_data:
                entities.append(
                    SenzomaticSensor(
                        coordinator=coordinator,
                        device_id=device_id,
                        device_name=device_name,
                        device_model=device_model,
                        sensor_type=SENSOR_REL_HUMIDITY,
                        name="Relative Humidity",
                        unit=PERCENTAGE,
                        device_class=SensorDeviceClass.HUMIDITY,
                        state_class=SensorStateClass.MEASUREMENT,
                    )
                )

            # Absolute humidity sensor
            if SENSOR_ABS_HUMIDITY in sensor_data:
                entities.append(
                    SenzomaticSensor(
                        coordinator=coordinator,
                        device_id=device_id,
                        device_name=device_name,
                        device_model=device_model,
                        sensor_type=SENSOR_ABS_HUMIDITY,
                        name="Absolute Humidity",
                        unit=UNIT_GRAMS_PER_M3,
                        device_class=SensorDeviceClass.HUMIDITY,
                        state_class=SensorStateClass.MEASUREMENT,
                    )
                )

            # Moisture sensor (only for devices that support it)
            if SENSOR_MOISTURE in sensor_data:
                entities.append(
                    SenzomaticSensor(
                        coordinator=coordinator,
                        device_id=device_id,
                        device_name=device_name,
                        device_model=device_model,
                        sensor_type=SENSOR_MOISTURE,
                        name="Wood Moisture",
                        unit=PERCENTAGE,
                        device_class=SensorDeviceClass.MOISTURE,
                        state_class=SensorStateClass.MEASUREMENT,
                    )
                )

    async_add_entities(entities)

class SenzomaticSensor(CoordinatorEntity, SensorEntity):
    """Representation of a Senzomatic sensor."""

    def __init__(
        self,
        coordinator: SenzomaticDataUpdateCoordinator,
        device_id: str,
        device_name: str,
        device_model: str,
        sensor_type: str,
        name: str,
        unit: str,
        device_class: SensorDeviceClass | None = None,
        state_class: SensorStateClass | None = None,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        
        self._device_id = device_id
        self._device_name = device_name
        self._device_model = device_model
        self._sensor_type = sensor_type
        self._attr_name = f"{device_name} {name}"
        self._attr_unique_id = f"{DOMAIN}_{device_id}_{sensor_type}"
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        self._attr_state_class = state_class

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            name=self._device_name,
            manufacturer="MoistureGuard",
            model=self._device_model,
            sw_version="1.0",
        )

    @property
    def native_value(self) -> float | None:
        """Return the native value of the sensor."""
        if not self.coordinator.data:
            return None
            
        sensor_data = self.coordinator.data.get("sensors", {}).get(self._device_id, {})
        value = sensor_data.get(self._sensor_type)
        
        if value is not None:
            return round(float(value), 2)
        
        return None

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return (
            self.coordinator.last_update_success
            and self.coordinator.data is not None
            and self._device_id in self.coordinator.data.get("sensors", {})
        ) 