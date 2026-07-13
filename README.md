# TP-Link Switch Bandwidth Monitor (Home Assistant Integration)
A Home Assistant integration to monitor bandwidth usage on TP-Link Easy Smart Switches.

## Features
✔ Real-time bandwidth monitoring (RX/TX Mbps)  
✔ Works with TP-Link TL-SG1016DE, TL-SG108E, and similar models  
✔ Polling interval & MTU adjustable at any time via the integration's **Configure** dialog  
✔ Home Assistant UI-based setup (no YAML required!)  
✔ Reauthentication flow if the switch password changes  
✔ Translations: English & Danish  

## Installation via HACS
1. Go to **HACS → Integrations → Custom Repositories**  
2. Add `https://github.com/bairnhard/ha-tplink-monitor` as an **Integration**  
3. Search for **"TP-Link Switch Bandwidth Monitor"** and install it  
4. Restart Home Assistant  
5. Add the integration from **Settings → Integrations**  

## Manual Installation
1. Copy `tplink_monitor/` to `/config/custom_components/`
2. Restart Home Assistant  
3. Add the integration via **Settings → Integrations**  

## Supported Switches
**TP-Link Easy Smart Switches:**
- TL-SG1016DE
- TL-SG108E
- TL-SG105E
- TL-SG1024DE  

## Options
After setup, open **Settings → Devices & Services → TP-Link Switch Bandwidth Monitor → Configure** to change:
- **Polling interval** (seconds between updates, default 15)
- **MTU size** (assumed average frame size used to estimate bandwidth, default 1500)

Changes take effect immediately — no reinstall or restart required.

## Notes
- **Your switch must have a static IP!**
- **Requires Home Assistant 2024.11 or newer** (uses modern config entry APIs)
