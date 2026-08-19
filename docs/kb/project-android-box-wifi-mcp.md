---
category: operations
---

# Android TV Box — WiFi Connection & MCP Server Notes

**Date:** 2026-06-25  
**Device:** Android TV box (`sailfish`)  
**WiFi target:** `TONY-WIFI_2.4G` / `TONY-WIFI_5G`  
**WiFi password:** `tonytony`  
**Device IP (Ethernet):** `192.168.1.43`  
**Device IP (WiFi):** `192.168.1.200`  

---

## Problem Summary

The Android TV box could not stay connected to `TONY-WIFI_2.4G`. The Android WiFi service would:

1. Authenticate successfully (`WPA2-PSK`, 4-way handshake complete).
2. Reach `COMPLETED` state.
3. Immediately disconnect with `reason=3` (locally generated disconnect) and `networkId=-1`.

`networkId=-1` indicated that the Android WiFi service could not map the wpa_supplicant network back to its internal `WifiConfigStore` network ID, so it tore the connection down.

---

## Root Cause

The Android WiFi service manages networks via its HAL, not by reading `wpa_supplicant.conf` directly. When we manually injected `TONY-WIFI_2.4G` into the configuration, wpa_supplicant used it and completed the WPA handshake, but the Android layer never saw a valid internal network ID for the connection. The HAL's state-change callbacks reported `nid=-1`, triggering the service to call `disconnect()`.

Two contributing factors:

- `wpa_cli` network activation commands (`enable_network`, `select_network`, `reconfigure`) returned `UNKNOWN COMMAND` / `FAIL` on the global control interface, which suggested the Android HAL and wpa_supplicant were not fully synchronized.
- The `wpa_supplicant` control interface was a file socket at `/data/vendor/wifi/wpa/sockets`, not the global `@android:wpa_wlan0` interface for some commands.

---

## Solution Implemented

### 1. Bypass the Android WiFi service for direct wpa_supplicant control

We disabled the Android WiFi service and ran `wpa_supplicant` directly with a manual config:

```bash
svc wifi disable
/vendor/bin/hw/wpa_supplicant -Dnl80211 -iwlan0 -c /data/vendor/wifi/wpa/wpa_supplicant_manual.conf -O /data/vendor/wifi/wpa/sockets -d -K
```

Manual config (`/data/vendor/wifi/wpa/wpa_supplicant_manual.conf`):

```text
ctrl_interface=/data/vendor/wifi/wpa/sockets
ctrl_interface_group=wifi
update_config=1
ap_scan=1
disabled_scan_offload=1

network={
    ssid="TONY-WIFI_2.4G"
    scan_ssid=1
    psk="tonytony"
    key_mgmt=WPA-PSK
    priority=1
}
```

Result:

- `wpa_cli -p /data/vendor/wifi/wpa/sockets -i wlan0 status` shows `wpa_state=COMPLETED`.
- Connection is to BSSID `98:00:6a:68:f7:c6` on channel 1 (`2412 MHz`).
- `key_mgmt=WPA2-PSK`, `pairwise_cipher=CCMP`, `group_cipher=CCMP`.

### 2. Assign static IP

The Android DHCP client does not run when the WiFi service is disabled. No DHCP client (`dhcpcd`, `dhclient`, `udhcpc`) was available on the system image.

We assigned a static IP outside the likely DHCP lease range:

```bash
ip addr flush dev wlan0
ip addr add 192.168.1.200/24 dev wlan0
ip link set wlan0 up
```

Verification:

```bash
ping -I wlan0 -c 3 192.168.1.1
# 0% packet loss
```

### 3. Create re-usable scripts

| File | Purpose |
|------|---------|
| `/data/vendor/wifi/wpa/wpa_supplicant_manual.conf` | Minimal wpa_supplicant config for `TONY-WIFI_2.4G` |
| `/data/local/tmp/wifi_manual.sh` | Full setup: disable Android WiFi, kill old wpa_supplicant, start new one, wait for `COMPLETED`, assign static IP |
| `/data/data/com.termux/files/home/.shortcuts/wifi_manual.sh` | Termux:Widget shortcut that runs the above as root |
| `/data/data/com.termux/files/home/.shortcuts/start_mcp.sh` | Termux:Widget shortcut to restart the MCP server |

---

## MCP Server Improvements

### Goal

Allow the MCP server to execute system-level commands as root, so we can manage `wpa_supplicant`, `WifiConfigStore`, and other privileged Android operations without needing ADB every time.

### Final Implementation

`run_shell` in `/data/data/com.termux/files/home/mcp_server.py` now supports a `root` parameter:

```python
if root:
    full_path = "/data/data/com.termux/files/usr/bin:/data/data/com.termux/files/usr/bin/applets:/system/bin:/vendor/bin:/system/xbin"
    cmd = f"su 0 -c {shlex.quote(f'PATH={full_path}:$PATH; ' + cmd)}"
```

The `shell` tool schema exposes the `root` boolean flag.

### Mistakes / False Starts

1. **Tried `su 0 /system/bin/sh -c <cmd>`**
   - This caused the Android `su` binary to drop everything after the first argument.
   - Result: `echo hello` returned empty, `wpa_cli ... status` entered interactive mode, `ifconfig wlan0` returned all interfaces.
   - **Fix:** Use `su 0 -c '<cmd>'`.

2. **Tried `export PATH=...; cmd` inside `su -c`**
   - `/system/bin/sh` on this device treated `export PATH=...;` in a way that printed the environment or failed to parse the assignment.
   - **Fix:** Set `PATH` directly as a shell variable before the command: `PATH=...; cmd`.

3. **Killing MCP server with `pkill -f mcp_server.py` or `ps -A | grep 'python mcp_server.py'`**
   - `ps -A` on this device truncates the command to just `python`.
   - `pkill -f` could match the script itself.
   - **Fix:** Use `ps -A | grep -E 'python.*mcp_server\.py'` and kill the listed PIDs.

### Verified Commands Over MCP

- `id` → `uid=0(root)`
- `wpa_cli -p /data/vendor/wifi/wpa/sockets -i wlan0 status | grep -E "wpa_state|ssid|..."`
- `ifconfig wlan0 | head -2`
- `ping -I wlan0 -c 2 192.168.1.1`

---

## Key Commands Reference

### Check WiFi status

```bash
wpa_cli -p /data/vendor/wifi/wpa/sockets -i wlan0 status
ifconfig wlan0
ip addr show wlan0
ip route | grep wlan0
```

### Reconnect manually

```bash
svc wifi disable
/data/local/tmp/wifi_manual.sh
```

### Restart MCP server

```bash
/data/data/com.termux/files/home/.shortcuts/start_mcp.sh
```

### Test MCP server

```python
import json, urllib.request
BASE = 'http://192.168.1.43:8080'
# Open /sse to get session_id, then POST to /message?session_id=...
```

---

## Important Notes

- The Android WiFi service is intentionally **disabled** to prevent it from tearing down the connection.
- The current IP is **static** (`192.168.1.200`). If the router DHCP range changes, this may need to be adjusted.
- The box still has Ethernet at `192.168.1.43`. Both interfaces share the `192.168.1.0/24` subnet; the default route is currently via `eth0`.
- To use WiFi as the primary path, either disconnect Ethernet or change the default route to `192.168.1.1 dev wlan0`.

---

## Open Items / Future Work

- Determine whether the Android WiFi service can be repaired so it manages the network properly again. This would require understanding why the internal `networkId` mapping failed and possibly rebuilding `WifiConfigStore.xml` from a clean state.
- Consider installing a DHCP client in Termux (e.g., `dhcpcd`) if dynamic IP assignment is preferred over static.
- Automate the manual WiFi setup on boot via `init.d` or a persistent Termux:Widget workflow.

---

## Hardware Information

| Component | Details |
|-----------|---------|
| **SoC / Board** | Rockchip RK3328 (`rockchip,rk3328-box-liantong-avb`) |
| **Build flavor** | `rk3328_box-userdebug` |
| **Device tree** | `Rockchip RK3328 box liantong avb` |
| **CPU** | ARM Cortex-A53 (implementer `0x41`, part `0xd03`) |
| **CPU cores** | 4 (aarch64, ARMv8) |
| **CPU features** | fp, asimd, evtstrm, aes, pmull, sha1, sha2, crc32, cpuid |
| **BogoMIPS** | 48.00 per core |
| **RAM** | 4 GB (`MemTotal: 4049476 kB`, ~3.8G usable) |
| **Swap** | ~2 GB |
| **Internal storage** | 64 GB eMMC (`mmcblk1`, 61071360 blocks ≈ 58.2 GiB) |
| **Data partition** | `/dev/block/mmcblk1p17` — 53G, 13% used |
| **System partition** | `/dev/block/dm-0` (apex overlay) |
| **Vendor partition** | `/dev/block/dm-1` — 120M, ~100% used |
| **GPU** | Mali (`ro.hardware.egl=mali`) |
| **Bootloader** | `rk30board` (reported as `unknown` in `ro.bootloader`) |
| **Kernel** | Linux 4.19.111 `#56 SMP PREEMPT aarch64` |
| **Kernel build date** | Mon Nov 16 17:36:14 CST 2020 |
| **Android version** | 10 (`QQ2A.200305.004.A1`) |
| **Security patch** | 2020-05-05 |
| **Build date** | Thu Nov 19 15:23:27 CST 2020 |
| **Build user/host** | `foxluo@hugsun02` |
| **ABI** | `arm64-v8a` (also supports `armeabi-v7a`, `armeabi`) |
| **Characteristics** | `tv` |
| **Google Play client ID** | `android-rockchip-tv` |
| **GMS version** | `10_201910` |

### Network Hardware

| Interface | MAC | Driver | Notes |
|-----------|-----|--------|-------|
| **WiFi** | `e0:76:d0:44:7f:f5` | `bcmsdh_sdmmc` | Broadcom `bcmdhd` module (1.5 MB) |
| **Ethernet** | `6c:5c:3d:0d:06:99` | `rk_gmac-dwmac` | Rockchip GMAC / DesignWare MAC |

### Display

| Property | Value |
|----------|-------|
| Resolution | 1920 × 1080 |
| Refresh rate | 60 Hz |
| Density | 213 dpi |
| Type | Built-in screen, internal touch |
| Color modes | 0 (default) |
| Secure content | Supported (`FLAG_SUPPORTS_PROTECTED_BUFFERS`) |

### Other Hardware

| Property | Value |
|----------|-------|
| **Sensors** | None (`No Sensors on the device`) |
| **Bluetooth** | Enabled and ON (`enabled: true`, `state: ON`); address `22:22:9E:65:01:00`, name `TONY-TV`; bonded device `TONY-XS` (`38:53:9C:AC:FB:30`). `config.disable_bluetooth=true` exists but only affects the UI toggle, not the adapter. |
| **USB** | Disconnected (host mode not active, no external device) |
| **Battery** | AC powered, level 100%, present flag `false` (no physical battery, likely always-on power) |
| **DRM** | Widevine / ClearKey services running (`drm.service.enabled=true`) |

## Glossary / Key Values

| Item | Value |
|------|-------|
| `wpa_supplicant` binary | `/vendor/bin/hw/wpa_supplicant` |
| `wpa_cli` binary | `/vendor/bin/wpa_cli` |
| Control socket path | `/data/vendor/wifi/wpa/sockets` |
| WiFi interface | `wlan0` |
| P2P interface | `p2p-dev-wlan0` |
| Android config store | `/data/misc/wifi/WifiConfigStore.xml` |
| Termux home | `/data/data/com.termux/files/home` |
| MCP server | `/data/data/com.termux/files/home/mcp_server.py` |
| MCP log | `/data/data/com.termux/files/home/mcp_server.log` |
| Termux:Widget shortcuts | `/data/data/com.termux/files/home/.shortcuts/` |
