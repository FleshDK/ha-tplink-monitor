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

# Hvor mange opdateringer der gaar mellem hver PoE-hentning.
POE_UPDATE_EVERY = 4


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
        # PoE-data aendrer sig langsomt, og hver hentning koster et login paa en
        # switch der kun tillader EEN session. Derfor hentes den kun hvert
        # POE_UPDATE_EVERY. opdatering - men altid foerste gang.
        self.poe_system: dict[str, Any] | None = None
        self.poe_supported: bool | None = None
        self._poe_ports: dict[int, dict[str, Any]] = {}
        self._poe_tick = 0

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

        await self._async_update_poe()
        for port, poe in self._poe_ports.items():
            if port in port_stats:
                port_stats[port].update(poe)

        return port_stats

    async def _async_update_poe(self) -> None:
        """Refresh the PoE data now and then.

        A PoE failure must never break the port statistics: the switch may not
        have PoE at all, and the previous values are better than nothing.
        """
        if self.poe_supported is False:
            return

        forfalden = self._poe_tick % POE_UPDATE_EVERY == 0 or not self._poe_ports
        self._poe_tick += 1
        if not forfalden:
            return

        try:
            poe = await self.hass.async_add_executor_job(self.client.fetch_poe)
        except TPLinkAuthError:
            raise
        except TPLinkMonitorError as err:
            _LOGGER.debug("PoE update failed, keeping previous values: %s", err)
            return

        if poe is None:
            _LOGGER.debug("Switch has no PoE page; not asking again")
            self.poe_supported = False
            return

        self.poe_supported = True
        self.poe_system = poe["system"]
        self._poe_ports = poe["ports"]
