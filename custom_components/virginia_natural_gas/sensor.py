"""Sensors for Virginia Natural Gas.

Daily usage and cost go into long-term statistics (see coordinator). These sensors
show the last billing period, the meter, and the current bill for dashboards and
automations.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfTime, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import BASE_URL, LOGIN_PAGE_PATH
from .const import DOMAIN
from .coordinator import VNGConfigEntry, VNGCoordinator, VNGData

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class VNGSensorDescription(SensorEntityDescription):
    """Describes a sensor."""

    value_fn: Callable[[VNGData], float | int | date | None]


def _ccf(**kwargs) -> dict:
    return {
        "device_class": SensorDeviceClass.GAS,
        "native_unit_of_measurement": UnitOfVolume.CENTUM_CUBIC_FEET,
        "suggested_display_precision": 0,
        **kwargs,
    }


def _dollars(**kwargs) -> dict:
    return {
        "device_class": SensorDeviceClass.MONETARY,
        "native_unit_of_measurement": "USD",
        "suggested_display_precision": 2,
        **kwargs,
    }


SENSORS: tuple[VNGSensorDescription, ...] = (
    VNGSensorDescription(
        key="meter_reading",
        translation_key="meter_reading",
        value_fn=lambda d: d.meter_reading,
        **_ccf(state_class=SensorStateClass.TOTAL_INCREASING),
    ),
    VNGSensorDescription(
        key="last_read_date",
        translation_key="last_read_date",
        device_class=SensorDeviceClass.DATE,
        value_fn=lambda d: d.last_read_date,
    ),
    VNGSensorDescription(
        key="next_read_date",
        translation_key="next_read_date",
        device_class=SensorDeviceClass.DATE,
        value_fn=lambda d: d.next_read_date,
    ),
    VNGSensorDescription(
        key="last_period_usage",
        translation_key="last_period_usage",
        value_fn=lambda d: d.last_period_usage,
        **_ccf(),
    ),
    VNGSensorDescription(
        key="last_period_days",
        translation_key="last_period_days",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.DAYS,
        value_fn=lambda d: d.last_period_days,
    ),
    VNGSensorDescription(
        key="last_period_cost",
        translation_key="last_period_cost",
        value_fn=lambda d: d.last_period_cost,
        **_dollars(),
    ),
    VNGSensorDescription(
        key="amount_due",
        translation_key="amount_due",
        value_fn=lambda d: d.summary.amount_due,
        **_dollars(),
    ),
    VNGSensorDescription(
        key="due_date",
        translation_key="due_date",
        device_class=SensorDeviceClass.DATE,
        value_fn=lambda d: d.summary.due_date,
    ),
    VNGSensorDescription(
        key="last_payment",
        translation_key="last_payment",
        value_fn=lambda d: d.summary.last_payment,
        **_dollars(),
    ),
    VNGSensorDescription(
        key="last_payment_date",
        translation_key="last_payment_date",
        device_class=SensorDeviceClass.DATE,
        value_fn=lambda d: d.summary.last_payment_date,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VNGConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensors."""
    coordinator = entry.runtime_data
    async_add_entities(VNGSensor(coordinator, description) for description in SENSORS)


class VNGSensor(CoordinatorEntity[VNGCoordinator], SensorEntity):
    """A Virginia Natural Gas sensor."""

    _attr_has_entity_name = True
    entity_description: VNGSensorDescription

    def __init__(self, coordinator: VNGCoordinator, description: VNGSensorDescription) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.unique_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id or entry.entry_id)},
            name="Virginia Natural Gas",
            manufacturer="Virginia Natural Gas",
            model="Gas meter",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=BASE_URL + LOGIN_PAGE_PATH,
        )

    @property
    def native_value(self) -> float | int | date | None:
        """Return the sensor value."""
        return self.entity_description.value_fn(self.coordinator.data)
