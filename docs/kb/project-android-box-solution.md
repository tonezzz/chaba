---
category: operations
---

# Solution Implemented

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

