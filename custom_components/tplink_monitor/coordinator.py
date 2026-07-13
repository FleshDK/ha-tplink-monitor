"""DataUpdateCoordinator for the TP-Link Switch Bandwidth Monitor integration."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_IP,
    CONF_MTU,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
    DEFAULT_MTU,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .tplink_monitor import (
    TPLinkAuthError,
    TPLinkMonitorError,
    TPLinkSwitchClient,
)

_LOGGER = logging.getLogger(__name__)


class TPLinkCoordinator(DataUpdateCoordinator[dict[int, dict[str, Any]]]):
    """Fetch TP-Link switch data at a configured interval."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator from a config entry."""
        scan_interval = entry.options.get(
            CONF_SCAN_INTERVAL,
            entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        )
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} ({entry.data[CONF_IP]})",
            config_entry=entry,
            update_interval=timedelta(seconds=scan_interval),
        )
        self.client = TPLinkSwitchClient(
            entry.data[CONF_IP],
            entry.data[CONF_USERNAME],
            entry.data[CONF_PASSWORD],
        )
        self.mtu: int = entry.options.get(
            CONF_MTU, entry.data.get(CONF_MTU, DEFAULT_MTU)
        )
        self.system_info: dict[str, str] | None = None

    async def _async_update_data(self) -> dict[int, dict[str, Any]]:
        """Fetch the latest port statistics from the switch."""
        try:
            port_stats = await self.hass.async_add_executor_job(
                self.client.fetch_port_statistics
            )
            if self.system_info is None:
                self.system_info = await self.hass.async_add_executor_job(
                    self.client.fetch_system_info
                )
        except TPLinkAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except TPLinkMonitorError as err:
            raise UpdateFailed(str(err)) from err

        return port_stats
