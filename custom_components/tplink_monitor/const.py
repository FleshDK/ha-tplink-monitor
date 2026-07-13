"""Constants for the TP-Link Switch Bandwidth Monitor integration."""

from homeassistant.const import Platform

DOMAIN = "tplink_monitor"

PLATFORMS: list[Platform] = [Platform.SENSOR]

DEFAULT_SCAN_INTERVAL = 15  # Default polling interval (seconds)
DEFAULT_MTU = 1500  # Default Ethernet frame size

MIN_SCAN_INTERVAL = 5
MAX_SCAN_INTERVAL = 3600
MIN_MTU = 576
MAX_MTU = 9216

CONF_IP = "ip"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_MTU = "mtu"
