"""Config flow for the TP-Link Switch Bandwidth Monitor integration."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr

from .const import (
    CONF_IP,
    CONF_MTU,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
    DEFAULT_MTU,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_MTU,
    MAX_SCAN_INTERVAL,
    MIN_MTU,
    MIN_SCAN_INTERVAL,
)
from .tplink_monitor import (
    TPLinkAuthError,
    TPLinkMonitorError,
    TPLinkSwitchClient,
)

_LOGGER = logging.getLogger(__name__)

USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_IP): str,
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


async def _validate_connection(
    hass: HomeAssistant, ip: str, username: str, password: str
) -> dict[str, str]:
    """Validate the credentials and return the switch system info."""
    client = TPLinkSwitchClient(ip, username, password)
    return await hass.async_add_executor_job(client.fetch_system_info)


class TPLinkConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for TP-Link Monitor."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                system_info = await _validate_connection(
                    self.hass,
                    user_input[CONF_IP],
                    user_input[CONF_USERNAME],
                    user_input[CONF_PASSWORD],
                )
            except TPLinkAuthError:
                errors["base"] = "invalid_auth"
            except TPLinkMonitorError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error during validation")
                errors["base"] = "unknown"
            else:
                mac = dr.format_mac(system_info["mac_address"])
                await self.async_set_unique_id(mac)
                self._abort_if_unique_id_configured(
                    updates={CONF_IP: user_input[CONF_IP]}
                )
                return self.async_create_entry(
                    title=f"TP-Link Switch ({system_info['device_model']})",
                    data=user_input,
                    options={
                        CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
                        CONF_MTU: DEFAULT_MTU,
                    },
                )

        return self.async_show_form(
            step_id="user", data_schema=USER_SCHEMA, errors=errors
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Handle reauthentication when the switch rejects the credentials."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for new credentials."""
        errors: dict[str, str] = {}
        reauth_entry = self._get_reauth_entry()

        if user_input is not None:
            try:
                await _validate_connection(
                    self.hass,
                    reauth_entry.data[CONF_IP],
                    user_input[CONF_USERNAME],
                    user_input[CONF_PASSWORD],
                )
            except TPLinkAuthError:
                errors["base"] = "invalid_auth"
            except TPLinkMonitorError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error during reauth")
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(
                    reauth_entry, data_updates=user_input
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> TPLinkOptionsFlowHandler:
        """Return the options flow handler."""
        return TPLinkOptionsFlowHandler()


class TPLinkOptionsFlowHandler(OptionsFlow):
    """Handle options flow for TP-Link Monitor."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        entry = self.config_entry
        current_scan_interval = entry.options.get(
            CONF_SCAN_INTERVAL,
            entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        )
        current_mtu = entry.options.get(
            CONF_MTU, entry.data.get(CONF_MTU, DEFAULT_MTU)
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_SCAN_INTERVAL, default=current_scan_interval
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL),
                    ),
                    vol.Optional(CONF_MTU, default=current_mtu): vol.All(
                        vol.Coerce(int), vol.Range(min=MIN_MTU, max=MAX_MTU)
                    ),
                }
            ),
        )
