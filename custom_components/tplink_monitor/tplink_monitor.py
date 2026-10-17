"""API client for TP-Link Easy Smart switches (web interface scraping)."""

from __future__ import annotations

import logging
import re
from typing import Any

import requests
from bs4 import BeautifulSoup

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT = 10

# TP-Link Status Mappings
TP_STATE = {0: "Disabled", 1: "Enabled"}
TP_LINK_STATUS = {
    0: "Link Down",
    2: "10M Half",
    3: "10M Full",
    5: "100M Full",
    6: "1000M Full",
}

# PoE-tabeller. Vaerdierne er laest direkte fra PoeConfigRpm.htm paa en
# TL-SG1016PE v5.20 og krydstjekket mod switchens egen web-UI.
TP_POE_STATE = {0: "Disabled", 1: "Enabled"}
TP_POE_PRIORITY = {0: "High", 1: "Middle", 2: "Low"}
TP_POE_STATUS = {
    0: "Off",
    1: "Turning on",
    2: "On",
    3: "Overload",
    4: "Short",
    5: "Nonstandard PD",
}

# Effekt og spaending leveres i tiendedele (86 = 8,6 W, 523 = 52,3 V),
# stroem i hele milliampere. Bekraeftet ved at regne efter: 52,3 V x 0,165 A
# = 8,63 W, og siden melder 86.
POE_TENTHS = 10.0


class TPLinkMonitorError(Exception):
    """Base error for the TP-Link monitor client."""


class TPLinkConnectionError(TPLinkMonitorError):
    """Raised when the switch cannot be reached."""


class TPLinkAuthError(TPLinkMonitorError):
    """Raised when login fails or the session is rejected."""


class TPLinkDataError(TPLinkMonitorError):
    """Raised when the switch response cannot be parsed."""


class TPLinkSwitchClient:
    """Minimal client for the Easy Smart switch web interface.

    The Easy Smart switches expose their data as JavaScript variables
    embedded in the HTML pages, so this client logs in and scrapes those
    values. All methods are blocking and must be run in an executor from
    Home Assistant.
    """

    def __init__(self, ip: str, username: str, password: str) -> None:
        """Initialize the client."""
        self._ip = ip
        self._username = username
        self._password = password

    def _login(self, session: requests.Session) -> None:
        """Log in to the switch web interface."""
        data = {"logon": "Login", "username": self._username, "password": self._password}
        try:
            response = session.post(
                f"http://{self._ip}/logon.cgi", data=data, timeout=REQUEST_TIMEOUT
            )
        except requests.Timeout as err:
            raise TPLinkConnectionError(
                f"Timeout connecting to {self._ip} after {REQUEST_TIMEOUT}s"
            ) from err
        except requests.RequestException as err:
            raise TPLinkConnectionError(f"Network error reaching {self._ip}: {err}") from err

        if response.status_code != 200:
            raise TPLinkAuthError(f"Login failed with HTTP {response.status_code}")

        # Newer Easy Smart firmware returns the logon page with an error
        # marker instead of a non-200 status code on bad credentials.
        if "logonInfo" in response.text:
            match = re.search(r"logonInfo\s*=\s*new\s+Array\(\s*(\d+)", response.text)
            if match and match.group(1) != "0":
                raise TPLinkAuthError("Switch rejected the credentials")

    def _get_page_script(self, session: requests.Session, page: str) -> str:
        """Fetch a page and return the first inline script block."""
        try:
            response = session.get(f"http://{self._ip}/{page}", timeout=REQUEST_TIMEOUT)
        except requests.Timeout as err:
            raise TPLinkConnectionError(
                f"Timeout fetching {page} from {self._ip} after {REQUEST_TIMEOUT}s"
            ) from err
        except requests.RequestException as err:
            raise TPLinkConnectionError(
                f"Network error fetching {page} from {self._ip}: {err}"
            ) from err

        if response.status_code != 200:
            raise TPLinkDataError(f"Failed to fetch {page} (HTTP {response.status_code})")

        soup = BeautifulSoup(response.text, "html.parser")
        script_tag = soup.find("script")
        if not script_tag or not script_tag.string:
            # The switch typically serves the logon page (without the data
            # script) when the session is not authenticated.
            raise TPLinkAuthError(f"No data script found in {page}; session likely rejected")

        return script_tag.string

    def _get_page_text(self, session: requests.Session, page: str) -> str:
        """Fetch a page and return the raw HTML.

        ``_get_page_script`` only returns the *first* inline script block, which
        is enough for the pages it was written for. The PoE page keeps its data
        in a later block, so this returns everything and lets the caller search.
        """
        try:
            response = session.get(f"http://{self._ip}/{page}", timeout=REQUEST_TIMEOUT)
        except requests.Timeout as err:
            raise TPLinkConnectionError(
                f"Timeout fetching {page} from {self._ip} after {REQUEST_TIMEOUT}s"
            ) from err
        except requests.RequestException as err:
            raise TPLinkConnectionError(
                f"Network error fetching {page} from {self._ip}: {err}"
            ) from err

        if response.status_code != 200:
            raise TPLinkDataError(f"Failed to fetch {page} (HTTP {response.status_code})")
        if "logonInfo" in response.text:
            raise TPLinkAuthError(f"Session rejected while fetching {page}")

        return response.text

    def fetch_port_statistics(self) -> dict[int, dict[str, Any]]:
        """Fetch and parse port statistics from the switch."""
        session = requests.Session()
        self._login(session)
        script_text = self._get_page_script(session, "PortStatisticsRpm.htm")

        pkts_match = re.search(r"pkts:\[(.*?)\]", script_text)
        state_match = re.search(r"state:\[(.*?)\]", script_text)
        link_match = re.search(r"link_status:\[(.*?)\]", script_text)
        max_port_num_match = re.search(r"var max_port_num = (\d+);", script_text)

        if not (pkts_match and state_match and link_match and max_port_num_match):
            raise TPLinkDataError("Port statistics page did not contain the expected data")

        pkts_values = [int(v) for v in pkts_match.group(1).split(",")]
        state_values = [int(v) for v in state_match.group(1).split(",")]
        link_values = [int(v) for v in link_match.group(1).split(",")]
        max_port_num = int(max_port_num_match.group(1))

        port_stats: dict[int, dict[str, Any]] = {}
        for i in range(max_port_num):
            port_stats[i + 1] = {
                "state": TP_STATE.get(state_values[i], "Unknown"),
                "link_status": TP_LINK_STATUS.get(link_values[i], "Unknown"),
                "tx_good": pkts_values[i * 4],
                "tx_bad": pkts_values[i * 4 + 1],
                "rx_good": pkts_values[i * 4 + 2],
                "rx_bad": pkts_values[i * 4 + 3],
            }

        return port_stats

    def fetch_system_info(self) -> dict[str, str]:
        """Fetch system info from the switch."""
        session = requests.Session()
        self._login(session)
        script_text = self._get_page_script(session, "SystemInfoRpm.htm")

        def extract_value(pattern: str) -> str:
            match = re.search(pattern, script_text, re.DOTALL)
            return match.group(1).strip() if match else "Unknown"

        info = {
            "device_model": extract_value(r'descriStr:\[\s*"([^"]+)"\s*\]'),
            "mac_address": extract_value(r'macStr:\[\s*"([^"]+)"\s*\]'),
            "ip_address": extract_value(r'ipStr:\[\s*"([^"]+)"\s*\]'),
            "subnet_mask": extract_value(r'netmaskStr:\[\s*"([^"]+)"\s*\]'),
            "default_gateway": extract_value(r'gatewayStr:\[\s*"([^"]+)"\s*\]'),
            "firmware_version": extract_value(r'firmwareStr:\[\s*"([^"]+)"\s*\]'),
            "hardware_version": extract_value(r'hardwareStr:\[\s*"([^"]+)"\s*\]'),
        }

        if info["mac_address"] == "Unknown":
            raise TPLinkDataError("Failed to extract MAC address from system info")

        return info

    def fetch_poe(self) -> dict[str, Any] | None:
        """Fetch PoE data, or None if this switch has no PoE page.

        Returns ``{"system": {...}, "ports": {1: {...}, ...}}``. Only the
        PoE-capable ports appear; on a TL-SG1016PE that is ports 1-8.
        """
        session = requests.Session()
        self._login(session)
        try:
            html = self._get_page_text(session, "PoeConfigRpm.htm")
        except TPLinkDataError:
            # Non-PoE models simply do not serve this page.
            return None

        def array(navn: str) -> list[int] | None:
            match = re.search(rf"{navn}\s*:\s*\[([^\]]*)\]", html)
            if not match:
                return None
            try:
                return [int(v) for v in match.group(1).split(",") if v.strip() != ""]
            except ValueError:
                return None

        def global_value(navn: str) -> int | None:
            match = re.search(rf"{navn}\s*:\s*(\d+)", html)
            return int(match.group(1)) if match else None

        state = array("state")
        power = array("power")
        current = array("current")
        voltage = array("voltage")
        if not (state and power and current and voltage):
            raise TPLinkDataError("PoE page did not contain the expected arrays")

        priority = array("priority") or []
        powerlimit = array("powerlimit") or []
        pdclass = array("pdclass") or []
        powerstatus = array("powerstatus") or []

        ports: dict[int, dict[str, Any]] = {}
        for i in range(len(state)):
            ports[i + 1] = {
                "poe_state": TP_POE_STATE.get(state[i], "Unknown"),
                "poe_priority": TP_POE_PRIORITY.get(
                    priority[i] if i < len(priority) else -1, "Unknown"
                ),
                "poe_power_limit": (powerlimit[i] / POE_TENTHS)
                if i < len(powerlimit)
                else None,
                "poe_power": power[i] / POE_TENTHS if i < len(power) else None,
                "poe_current": current[i] if i < len(current) else None,
                "poe_voltage": voltage[i] / POE_TENTHS if i < len(voltage) else None,
                "poe_status": TP_POE_STATUS.get(
                    powerstatus[i] if i < len(powerstatus) else -1, "Unknown"
                ),
                "poe_class_raw": pdclass[i] if i < len(pdclass) else None,
            }

        system: dict[str, Any] = {}
        for noegle, navn in (
            ("limit", "system_power_limit"),
            ("consumption", "system_power_consumption"),
            ("remain", "system_power_remain"),
        ):
            raw = global_value(navn)
            system[noegle] = raw / POE_TENTHS if raw is not None else None

        _LOGGER.debug(
            "PoE: %d ports, %.1f W of %.1f W in use",
            len(ports),
            system.get("consumption") or 0.0,
            system.get("limit") or 0.0,
        )
        return {"system": system, "ports": ports}
