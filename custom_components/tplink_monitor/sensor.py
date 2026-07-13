"""Sensor platform for the TP-Link Switch Bandwidth Monitor integration."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfDataRate
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import TPLinkCoordinator

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class TPLinkPortSensorDescription(SensorEntityDescription):
    """Describes a per-port TP-Link sensor derived from the coordinator data."""

    value_fn: Callable[[dict[str, Any]], Any]


# Descriptions for the counter/status sensors. The bandwidth sensor is handled
# separately because it needs stateful rate calculation between updates.
PORT_SENSOR_DESCRIPTIONS: tuple[TPLinkPortSensorDescription, ...] = (
    TPLinkPortSensorDescription(
        key="link_speed",
        name="Link Speed",
        icon="mdi:speedometer",
        value_fn=lambda port: port["link_status"],
    ),
    TPLinkPortSensorDescription(
        key="rx_errors",
        name="RX Errors",
        icon="mdi:alert-circle-outline",
        native_unit_of_measurement="packets",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda port: port["rx_bad"],
    ),
    TPLinkPortSensorDescription(
        key="tx_errors",
        name="TX Errors",
        icon="mdi:alert-circle-outline",
        native_unit_of_measurement="packets",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda port: port["tx_bad"],
    ),
    TPLinkPortSensorDescription(
        key="rx_packets",
        name="RX Packets",
        icon="mdi:download-network-outline",
        native_unit_of_measurement="packets",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda port: port["rx_good"],
    ),
    TPLinkPortSensorDescription(
        key="tx_packets",
        name="TX Packets",
        icon="mdi:upload-network-outline",
        native_unit_of_measurement="packets",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda port: port["tx_good"],
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up TP-Link sensors from a config entry."""
    coordinator: TPLinkCoordinator = entry.runtime_data

    system_info = coordinator.system_info
    if not system_info:
        _LOGGER.error("System info missing; cannot set up port sensors")
        return

    ports = sorted(coordinator.data) if coordinator.data else list(range(1, 17))
    _LOGGER.debug("Creating sensors for %d ports", len(ports))

    entities: list[SensorEntity] = []
    for port in ports:
        entities.append(TplinkPortBandwidthSensor(coordinator, port, system_info))
        entities.extend(
            TplinkPortSensor(coordinator, port, system_info, description)
            for description in PORT_SENSOR_DESCRIPTIONS
        )

    async_add_entities(entities)


def _build_device_info(mac: str, system_info: dict[str, str]) -> DeviceInfo:
    """Return shared device info for all port entities."""
    return DeviceInfo(
        identifiers={(DOMAIN, mac)},
        connections={(CONNECTION_NETWORK_MAC, mac)},
        name=f"TP-Link Switch ({system_info['device_model']})",
        manufacturer="TP-Link",
        model=system_info["device_model"],
        sw_version=system_info["firmware_version"],
        hw_version=system_info["hardware_version"],
        configuration_url=f"http://{system_info['ip_address']}",
    )


class TplinkPortSensor(CoordinatorEntity[TPLinkCoordinator], SensorEntity):
    """A per-port sensor driven by a description (link speed, counters, errors)."""

    _attr_has_entity_name = True
    entity_description: TPLinkPortSensorDescription

    def __init__(
        self,
        coordinator: TPLinkCoordinator,
        port: int,
        system_info: dict[str, str],
        description: TPLinkPortSensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._port = port
        self._device_mac = system_info["mac_address"]
        self._attr_name = f"Port {port} {description.name}"
        self._attr_unique_id = f"{self._device_mac}_port_{port}_{description.key}"
        self._attr_device_info = _build_device_info(self._device_mac, system_info)

    @property
    def available(self) -> bool:
        """Return True if the port data is available."""
        return (
            super().available
            and self.coordinator.data is not None
            and self._port in self.coordinator.data
        )

    @property
    def native_value(self) -> Any:
        """Return the value for this sensor from the coordinator data."""
        data = self.coordinator.data
        if not data or self._port not in data:
            return None
        return self.entity_description.value_fn(data[self._port])


class TplinkPortBandwidthSensor(CoordinatorEntity[TPLinkCoordinator], SensorEntity):
    """Estimated bandwidth for a single switch port (RX + TX)."""

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.DATA_RATE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfDataRate.MEGABITS_PER_SECOND

    def __init__(
        self,
        coordinator: TPLinkCoordinator,
        port: int,
        system_info: dict[str, str],
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._port = port
        self._device_mac = system_info["mac_address"]
        self._attr_name = f"Port {port} Bandwidth"
        # Keep the original unique_id so existing installs are preserved.
        self._attr_unique_id = f"{self._device_mac}_port_{port}"
        self._attr_device_info = _build_device_info(self._device_mac, system_info)
        self._prev_rx_good: int | None = None
        self._prev_tx_good: int | None = None
        self._rx_mbps = 0.0
        self._tx_mbps = 0.0
        self._attr_native_value = 0.0

    @property
    def available(self) -> bool:
        """Return True if the port data is available."""
        return (
            super().available
            and self.coordinator.data is not None
            and self._port in self.coordinator.data
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Recalculate the bandwidth when new data arrives."""
        data = self.coordinator.data
        if data and self._port in data:
            rx_good = data[self._port]["rx_good"]
            tx_good = data[self._port]["tx_good"]

            if self._prev_rx_good is not None and self._prev_tx_good is not None:
                time_diff = self.coordinator.update_interval.total_seconds()
                mtu = self.coordinator.mtu
                self._rx_mbps = max(
                    0.0, (rx_good - self._prev_rx_good) * mtu * 8 / (time_diff * 1e6)
                )
                self._tx_mbps = max(
                    0.0, (tx_good - self._prev_tx_good) * mtu * 8 / (time_diff * 1e6)
                )
                self._attr_native_value = round(self._rx_mbps + self._tx_mbps, 2)

            self._prev_rx_good = rx_good
            self._prev_tx_good = tx_good

        super()._handle_coordinator_update()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional switch statistics."""
        data = self.coordinator.data
        if not data or self._port not in data:
            return {}

        return {
            "state": data[self._port]["state"],
            "link_status": data[self._port]["link_status"],
            "rx_good": data[self._port]["rx_good"],
            "tx_good": data[self._port]["tx_good"],
            "rx_bad": data[self._port]["rx_bad"],
            "tx_bad": data[self._port]["tx_bad"],
            "rx_mbps": round(self._rx_mbps, 2),
            "tx_mbps": round(self._tx_mbps, 2),
        }
