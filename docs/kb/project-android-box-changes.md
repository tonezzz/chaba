---
project: android-box
date: 2026-07-21
tags: [changelog]
status: active
---

# Android TV box — Change log

| Date | Change | Reason | Result | Reference |
|------|--------|--------|--------|-----------|
| 2026-06-25 | Disabled Android WiFi service; ran `wpa_supplicant` manually with static config | Android WiFi service kept disconnecting (`networkId=-1`) because it could not map the injected network to its internal `WifiConfigStore` | Stable WiFi connection to `TONY-WIFI_2.4G` at `192.168.1.200` | `projects/android-box/README.md` |
| 2026-06-25 | Assigned static IP `192.168.1.200/24` to `wlan0` | No DHCP client available when Android WiFi service is disabled | Box reachable on both Ethernet (`192.168.1.43`) and WiFi (`192.168.1.200`) | `projects/android-box/README.md` |
| 2026-06-25 | Added `root` boolean to MCP `run_shell` tool | Needed system-level commands (e.g., `wpa_cli`, `ifconfig`) without ADB every time | Commands can run as root over MCP | `projects/android-box/README.md` |
| 2026-06-25 | Created Termux:Widget shortcuts for `wifi_manual.sh` and `start_mcp.sh` | Make manual WiFi setup and MCP restart one-tap operations on the device | Easier recovery if WiFi/MCP stops | `projects/android-box/README.md` |

## Open items

- Repair or replace the Android WiFi service so it manages networks normally again.
- Consider a DHCP client in Termux if dynamic IP is preferred.
- Automate the manual WiFi setup on boot.
