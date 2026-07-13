"""The TP-Link Switch Bandwidth Monitor integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN, PLATFORMS
from .coordinator import TPLinkCoordinator

_LOGGER = logging.getLogger(__name__)

TPLinkMonitorConfigEntry = ConfigEntry[TPLinkCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: TPLinkMonitorConfigEntry) -> bool:
    """Set up TP-Link Monitor from a config entry."""
    coordinator = TPLinkCoordinator(hass, entry)

    # Fetch initial data (also fetches system info) so entities are
    # available right away; raises ConfigEntryNotReady on failure.
    await coordinator.async_config_entry_first_refresh()

    system_info = coordinator.system_info
    if system_info:
        device_registry = dr.async_get(hass)
        device_registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, system_info["mac_address"])},
            connections={(dr.CONNECTION_NETWORK_MAC, system_info["mac_address"])},
            manufacturer="TP-Link",
            name=f"TP-Link Switch ({system_info['device_model']})",
            model=system_info["device_model"],
            sw_version=system_info["firmware_version"],
            hw_version=system_info["hardware_version"],
            configuration_url=f"http://{system_info['ip_address']}",
        )

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Reload the entry when options (polling interval, MTU) change.
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def _async_update_listener(hass: HomeAssistant, entry: TPLinkMonitorConfigEntry) -> None:
    """Handle options update by reloading the entry."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: TPLinkMonitorConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
