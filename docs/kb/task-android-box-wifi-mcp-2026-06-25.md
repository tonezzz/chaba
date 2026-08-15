# Task: Android TV Box WiFi Connection + MCP Server

**Created:** 2026-06-25  
**Device:** Android TV box (`sailfish` / `rk3328_box`)  
**Device IP (Ethernet):** `192.168.1.43`  
**Target SSID:** `TONY-WIFI_2.4G` (also `TONY-WIFI_5G` kept in config)  
**WiFi password:** `tonytony`  
**Final WiFi IP:** `192.168.1.200`  

---

## Goal

1. Establish a working WiFi connection to `TONY-WIFI_2.4G`.
2. Improve the MCP server so it can execute root/system-level commands more efficiently than repeated ADB.
3. Document everything so the process can be repeated or reused.

---

## Pre-requisites

- ADB access to the box over Ethernet or USB.
- ADB root: `adb root` works.
- Termux installed on the box.
- Termux:Widget installed (optional but useful for shortcuts).
- Existing MCP server at `/data/data/com.termux/files/home/mcp_server.py`.
- Box is already rooted (`su` binary present, root shell available).

---

## Part 1 — Initial Diagnosis

### 1.1 Check the current WiFi state

```bash
adb shell
su
wpa_cli -p /data/vendor/wifi/wpa/sockets -i wlan0 status
wpa_cli -p /data/vendor/wifi/wpa/sockets -i wlan0 list_networks
wpa_cli -p /data/vendor/wifi/wpa/sockets -i wlan0 scan_results
ifconfig wlan0
ifconfig eth0
ip route
```

### 1.2 Pull the Android WiFi config

```bash
adb root
adb shell 'su -c "cp /data/misc/wifi/WifiConfigStore.xml /sdcard/WifiConfigStore.xml && chmod 644 /sdcard/WifiConfigStore.xml"'
adb pull /sdcard/WifiConfigStore.xml /tmp/WifiConfigStore.xml
```

### 1.3 Check Android WiFi service state

```bash
adb shell 'dumpsys wifi | grep -a -iE "SSID|Supplicant state|curState|mNetworkInfo|ConfiguredNetworks|NetworkSelectionStatus|recentFailure" | head -40'
```

### 1.4 What we found

- Android WiFi service had the two target networks (`TONY-WIFI_2.4G`, `TONY-WIFI_5G`) in `WifiConfigStore.xml`.
- `wpa_supplicant` was running but the connection kept reaching `COMPLETED` and then disconnecting.
- `dumpsys wifi` showed `NETWORK_DISCONNECTION_EVENT ... nid=1 reason=3` and state callbacks with `nid=-1`.
- `reason=3` = locally generated disconnect (the Android WiFi service told wpa_supplicant to disconnect).
- Root cause: the Android WiFi service could not map the wpa_supplicant network ID to its internal network ID, so it rejected the connection.

---

## Part 2 — Fix Attempts (recorded for learning)

### 2.1 Tried to push a clean `WifiConfigStore.xml`

Created a minimal `WifiConfigStore_enabled.xml` with only the two target networks. Pushed it:

```bash
adb push /tmp/WifiConfigStore_enabled.xml /sdcard/WifiConfigStore_enabled.xml
adb shell 'su -c "cp /sdcard/WifiConfigStore_enabled.xml /data/misc/wifi/WifiConfigStore.xml && chmod 660 /data/misc/wifi/WifiConfigStore.xml && chown wifi:wifi /data/misc/wifi/WifiConfigStore.xml"'
adb shell 'su -c "killall -9 wpa_supplicant wificond 2>/dev/null; svc wifi disable; sleep 2; svc wifi enable"'
```

**Result:** The Android service still reported `networkId=-1` and disconnected.

### 2.2 Tried direct `wpa_cli` commands

```bash
wpa_cli -p /data/vendor/wifi/wpa/sockets -i wlan0 remove_network all
wpa_cli -p /data/vendor/wifi/wpa/sockets -i wlan0 add_network
wpa_cli -p /data/vendor/wifi/wpa/sockets -i wlan0 set_network 0 ssid '"TONY-WIFI_2.4G"'
wpa_cli -p /data/vendor/wifi/wpa/sockets -i wlan0 set_network 0 psk '"tonytony"'
wpa_cli -p /data/vendor/wifi/wpa/sockets -i wlan0 enable_network 0
wpa_cli -p /data/vendor/wifi/wpa/sockets -i wlan0 select_network 0
```

**Result:** Some commands worked, some (`enable_network`, `select_network`, `reconfigure`) returned `UNKNOWN COMMAND` or `FAIL` on the global interface. The interaction between the Android HAL and wpa_supplicant was inconsistent.

### 2.3 Tried toggling WiFi

```bash
adb shell 'svc wifi disable && sleep 3 && svc wifi enable'
```

**Result:** This triggered the Android service to attempt a connection. It reached `ASSOCIATING -> ASSOCIATED -> COMPLETED`, but still disconnected with `networkId=-1`.

---

## Part 3 — Working Solution

### 3.1 Decision

Bypass the Android WiFi service entirely. Disable it, run `wpa_supplicant` directly with a manual config, and assign a static IP.

### 3.2 Disable Android WiFi service

```bash
adb shell 'svc wifi disable'
```

### 3.3 Create the manual `wpa_supplicant.conf`

File: `/tmp/wpa_supplicant_manual.conf`

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

Push it:

```bash
adb push /tmp/wpa_supplicant_manual.conf /data/vendor/wifi/wpa/wpa_supplicant_manual.conf
adb shell 'chmod 644 /data/vendor/wifi/wpa/wpa_supplicant_manual.conf && chown wifi:wifi /data/vendor/wifi/wpa/wpa_supplicant_manual.conf'
```

### 3.4 Stop any existing wpa_supplicant

```bash
adb shell 'su -c "for pid in \$(ps -A | grep wpa_supplicant | grep -v grep | awk \"{print \\\$2}\"); do kill -9 \$pid 2>/dev/null; done"'
```

### 3.5 Start wpa_supplicant manually

```bash
adb shell '/vendor/bin/hw/wpa_supplicant -Dnl80211 -iwlan0 -c /data/vendor/wifi/wpa/wpa_supplicant_manual.conf -O /data/vendor/wifi/wpa/sockets -d -K > /data/vendor/wifi/wpa/wifi_manual.log 2>&1 &'
```

### 3.6 Verify association

```bash
adb shell 'wpa_cli -p /data/vendor/wifi/wpa/sockets -i wlan0 status'
```

Expected output:

```text
bssid=98:00:6a:68:f7:c6
freq=2412
ssid=TONY-WIFI_2.4G
key_mgmt=WPA2-PSK
wpa_state=COMPLETED
address=e0:76:d0:44:7f:f5
```

### 3.7 Assign static IP

No DHCP client exists on the system image, so we used a static IP.

```bash
adb shell 'su -c "ip addr flush dev wlan0 && ip addr add 192.168.1.200/24 dev wlan0 && ip link set wlan0 up"'
```

### 3.8 Verify connectivity

```bash
adb shell 'ping -I wlan0 -c 3 192.168.1.1'
```

Expected: `0% packet loss`.

---

## Part 4 — Automation Scripts

### 4.1 Full WiFi setup script

File: `/data/local/tmp/wifi_manual.sh`

```bash
#!/system/bin/sh
# Manual WiFi setup for Android box (bypasses Android WiFi service)

set -e

WPA=/vendor/bin/hw/wpa_supplicant
CONF=/data/vendor/wifi/wpa/wpa_supplicant_manual.conf
SOCK=/data/vendor/wifi/wpa/sockets
IFACE=wlan0
IP=192.168.1.200/24

echo "[*] Disabling Android WiFi service..."
svc wifi disable
sleep 2

echo "[*] Stopping any existing wpa_supplicant..."
for pid in $(ps -A | grep wpa_supplicant | grep -v grep | awk '{print $2}'); do
    kill -9 "$pid" 2>/dev/null || true
done
sleep 2

echo "[*] Starting wpa_supplicant..."
$WPA -Dnl80211 -i$IFACE -c $CONF -O $SOCK -d -K > /data/vendor/wifi/wpa/wifi_manual.log 2>&1 &

echo "[*] Waiting for association..."
for i in $(seq 1 30); do
    sleep 2
    STATE=$(wpa_cli -p $SOCK -i $IFACE status 2>/dev/null | grep wpa_state | cut -d= -f2 || echo "UNKNOWN")
    echo "    state: $STATE"
    [ "$STATE" = "COMPLETED" ] && break
done

[ "$STATE" != "COMPLETED" ] && { echo "[!] Failed to associate"; exit 1; }

echo "[*] Configuring static IP $IP..."
ip addr flush dev $IFACE 2>/dev/null || true
ip addr add $IP dev $IFACE
ip link set $IFACE up

echo "[*] WiFi connected!"
wpa_cli -p $SOCK -i $IFACE status | grep -E "ssid|bssid|wpa_state|key_mgmt|freq|ip_address"
```

Push it:

```bash
adb push /tmp/wifi_manual.sh /data/local/tmp/wifi_manual.sh
adb shell 'chmod 755 /data/local/tmp/wifi_manual.sh && chown root:root /data/local/tmp/wifi_manual.sh'
```

### 4.2 Termux:Widget shortcut

File: `/data/data/com.termux/files/home/.shortcuts/wifi_manual.sh`

```bash
#!/data/data/com.termux/files/usr/bin/bash
export PATH=/data/data/com.termux/files/usr/bin:/data/data/com.termux/files/usr/bin/applets:/system/bin:/vendor/bin:$PATH
su -c /data/local/tmp/wifi_manual.sh
```

```bash
adb shell 'cat > /data/data/com.termux/files/home/.shortcuts/wifi_manual.sh <<EOF
#!/data/data/com.termux/files/usr/bin/bash
export PATH=/data/data/com.termux/files/usr/bin:/data/data/com.termux/files/usr/bin/applets:/system/bin:/vendor/bin:$PATH
su -c /data/local/tmp/wifi_manual.sh
EOF
chmod 755 /data/data/com.termux/files/home/.shortcuts/wifi_manual.sh
chown u0_a81:u0_a81 /data/data/com.termux/files/home/.shortcuts/wifi_manual.sh'
```

---

## Part 5 — MCP Server Improvements

### 5.1 Goal

Allow the MCP server to run shell commands as root so we can manage the box without ADB.

### 5.2 Key code changes

File: `/data/data/com.termux/files/home/mcp_server.py`

In `run_shell()`:

```python
import shlex

def run_shell(cmd, timeout=30, root=False):
    if root:
        full_path = "/data/data/com.termux/files/usr/bin:/data/data/com.termux/files/usr/bin/applets:/system/bin:/vendor/bin:/system/xbin"
        cmd = f"su 0 -c {shlex.quote(f'PATH={full_path}:$PATH; ' + cmd)}"
    # ... rest of subprocess.run
```

In the `shell` tool schema:

```json
"root": {"type": "boolean", "description": "Run as root via su (device must be rooted)"}
```

In `handle_tool_call()`:

```python
root = args.get("root", False)
return [run_shell(cmd, timeout, root=root)]
```

### 5.3 The critical mistake

We initially used:

```python
cmd = f"su 0 /system/bin/sh -c {shlex.quote(cmd)}"
```

This Android `su` binary dropped all command arguments after the first word. Symptoms:

- `echo hello` returned empty.
- `wpa_cli ... status` entered interactive mode.
- `ifconfig wlan0` returned all interfaces.

**Fix:** Use `su 0 -c '<cmd>'`.

### 5.4 Start MCP server script

File: `/data/data/com.termux/files/home/.shortcuts/start_mcp.sh`

```bash
#!/data/data/com.termux/files/usr/bin/bash
export PATH=/data/data/com.termux/files/usr/bin:/data/data/com.termux/files/usr/bin/applets:/system/bin:/vendor/bin:$PATH
export HOME=/data/data/com.termux/files/home
export PREFIX=/data/data/com.termux/files/usr
cd /data/data/com.termux/files/home

# kill old server
for pid in $(ps -A | grep -E 'python.*mcp_server\.py' | grep -v grep | awk '{print $2}'); do
    kill -9 "$pid" 2>/dev/null || true
done
sleep 1

nohup /data/data/com.termux/files/usr/bin/python mcp_server.py > mcp_server.log 2>&1 &
echo "MCP server started on port 8080"
```

### 5.5 Verify MCP server

```bash
# Listens on port 8080
adb shell 'netstat -tlnp | grep 8080'

# Test via Python
import json, urllib.request
BASE = 'http://192.168.1.43:8080'
```

Example MCP call:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "shell",
    "arguments": {
      "command": "wpa_cli -p /data/vendor/wifi/wpa/sockets -i wlan0 status | grep wpa_state",
      "root": true
    }
  }
}
```

---

## Part 6 — Complete Reset / Redo Procedure

If you need to redo everything from scratch, run these commands in order:

```bash
# 1. ADB root
adb root

# 2. Push wpa_supplicant config
adb push /tmp/wpa_supplicant_manual.conf /data/vendor/wifi/wpa/wpa_supplicant_manual.conf
adb shell 'chmod 644 /data/vendor/wifi/wpa/wpa_supplicant_manual.conf && chown wifi:wifi /data/vendor/wifi/wpa/wpa_supplicant_manual.conf'

# 3. Push WiFi setup script
adb push /tmp/wifi_manual.sh /data/local/tmp/wifi_manual.sh
adb shell 'chmod 755 /data/local/tmp/wifi_manual.sh && chown root:root /data/local/tmp/wifi_manual.sh'

# 4. Push Termux shortcut
adb shell 'cat > /data/data/com.termux/files/home/.shortcuts/wifi_manual.sh <<EOF
#!/data/data/com.termux/files/usr/bin/bash
export PATH=/data/data/com.termux/files/usr/bin:/data/data/com.termux/files/usr/bin/applets:/system/bin:/vendor/bin:$PATH
su -c /data/local/tmp/wifi_manual.sh
EOF
chmod 755 /data/data/com.termux/files/home/.shortcuts/wifi_manual.sh
chown u0_a81:u0_a81 /data/data/com.termux/files/home/.shortcuts/wifi_manual.sh'

# 5. Push updated MCP server
adb push /tmp/mcp_server.py /data/data/com.termux/files/home/mcp_server.py
adb shell 'chown u0_a81:u0_a81 /data/data/com.termux/files/home/mcp_server.py && chmod 755 /data/data/com.termux/files/home/mcp_server.py'

# 6. Start MCP server
adb shell 'cat > /data/data/com.termux/files/home/.shortcuts/start_mcp.sh <<EOF
#!/data/data/com.termux/files/usr/bin/bash
export PATH=/data/data/com.termux/files/usr/bin:/data/data/com.termux/files/usr/bin/applets:/system/bin:/vendor/bin:$PATH
export HOME=/data/data/com.termux/files/home
export PREFIX=/data/data/com.termux/files/usr
cd /data/data/com.termux/files/home
for pid in \$(ps -A | grep -E "python.*mcp_server\\.py" | grep -v grep | awk "{print \$2}"); do
    kill -9 "\$pid" 2>/dev/null || true
done
sleep 1
nohup /data/data/com.termux/files/usr/bin/python mcp_server.py > mcp_server.log 2>&1 &
echo "MCP server started on port 8080"
EOF
chmod 755 /data/data/com.termux/files/home/.shortcuts/start_mcp.sh
chown u0_a81:u0_a81 /data/data/com.termux/files/home/.shortcuts/start_mcp.sh'

# 7. Connect WiFi
adb shell 'su -c /data/local/tmp/wifi_manual.sh'

# 8. Verify
adb shell 'wpa_cli -p /data/vendor/wifi/wpa/sockets -i wlan0 status | grep -E "wpa_state|ssid|ip_address|bssid"'
adb shell 'ping -I wlan0 -c 3 192.168.1.1'
```

---

## Part 7 — Suggested Improvements

### 7.1 Use a DHCP client instead of static IP

The current setup uses static IP `192.168.1.200`. If the router DHCP range changes or another device takes that IP, there will be a conflict.

Options:

- Install `dhcpcd` in Termux and run it on `wlan0` after association.
- Compile or push a static `udhcpc` binary.
- Use Android's `netd` / `dhcpcd` if available, but this requires the Android WiFi service to be enabled.

### 7.2 Repair the Android WiFi service instead of bypassing it

Bypassing the Android service is a workaround. A cleaner fix would be to make the Android WiFi service properly recognize the network:

- Clear `/data/misc/wifi/WifiConfigStore.xml` and `/data/misc/wifi/WifiConfigStoreSoftAp.xml`.
- Reboot and let the service recreate the config.
- Add the network via Android settings or `cmd wifi` (if available on this build).
- Investigate why the HAL network ID mapping failed — possible causes:
  - Mismatched `id_str` in wpa_supplicant.
  - Corrupted `WifiConfigStore.xml`.
  - Stale wpa_supplicant control socket.

### 7.3 Automate on boot

Currently the user must tap the Termux:Widget shortcut after reboot. To make this fully automatic:

- Add an `init.d` script if the device supports it.
- Use a Magisk module with a `service.sh` that runs after boot.
- Use Tasker or a custom boot receiver app to trigger the Termux shortcut.

### 7.4 Improve MCP server robustness

- Close SSE connections properly to avoid `CLOSE_WAIT` sockets piling up.
- Add a health-check endpoint or heartbeat.
- Add authentication or bind to a specific interface if exposed beyond the LAN.
- Add a `start_wifi` tool that calls `/data/local/tmp/wifi_manual.sh` directly.
- Add a `get_wifi_status` tool for quick diagnostics.

### 7.5 Better process management

- Use a PID file for the MCP server and wpa_supplicant so they can be restarted cleanly.
- Consider running `wpa_supplicant` under `nohup` or as a service so it survives the launching shell closing.

### 7.6 Documentation improvements

- Add a network diagram showing Ethernet vs WiFi routing.
- Record the exact router model and DHCP range.
- Add a "decision tree" for choosing Android WiFi service vs manual bypass.
- Keep the KB note and task file in sync.

---

## Part 8 — Quick Reference

| Check | Command |
|-------|---------|
| WiFi status | `wpa_cli -p /data/vendor/wifi/wpa/sockets -i wlan0 status` |
| WiFi networks | `wpa_cli -p /data/vendor/wifi/wpa/sockets -i wlan0 list_networks` |
| Scan results | `wpa_cli -p /data/vendor/wifi/wpa/sockets -i wlan0 scan_results` |
| Interface IP | `ifconfig wlan0` or `ip addr show wlan0` |
| Gateway ping | `ping -I wlan0 -c 3 192.168.1.1` |
| Routes | `ip route` |
| Android WiFi service | `svc wifi disable` / `svc wifi enable` |
| MCP server | `ps -A \| grep -i python` / `netstat -tlnp \| grep 8080` |

| Path | Purpose |
|------|---------|
| `/data/vendor/wifi/wpa/wpa_supplicant_manual.conf` | Manual wpa_supplicant config |
| `/data/vendor/wifi/wpa/wifi_manual.log` | Manual wpa_supplicant log |
| `/data/local/tmp/wifi_manual.sh` | WiFi setup script |
| `/data/data/com.termux/files/home/mcp_server.py` | MCP server |
| `/data/data/com.termux/files/home/mcp_server.log` | MCP server log |
| `/data/data/com.termux/files/home/.shortcuts/wifi_manual.sh` | Termux:Widget WiFi shortcut |
| `/data/data/com.termux/files/home/.shortcuts/start_mcp.sh` | Termux:Widget MCP shortcut |
| `/data/misc/wifi/WifiConfigStore.xml` | Android WiFi config store |

---

## Appendix — MCP Server Specification

This section describes the MCP (Model Context Protocol) server implemented in `/data/data/com.termux/files/home/mcp_server.py`. It is a minimal HTTP/SSE-based server using only the Python standard library.

### Server details

| Property | Value |
|----------|-------|
| Host | `0.0.0.0` |
| Port | `8080` |
| Protocol | MCP over HTTP/SSE with JSON-RPC |
| Protocol version | `2024-11-05` |
| Server name | `android-box-mcp` |
| Version | `0.1.0` |

### Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/sse` | `GET` | Open a Server-Sent Events stream. The server returns an `endpoint` event containing the session-specific message URL. |
| `/message?session_id=<id>` | `POST` | Send JSON-RPC requests for the session. The server processes them asynchronously and pushes responses over the SSE stream. |

### Session flow

1. Client opens `GET /sse`.
2. Server responds with an event stream and sends:
   ```text
   event: endpoint
   data: /message?session_id=sess-<timestamp>-<thread_id>
   ```
3. Client sends JSON-RPC requests to `POST /message?session_id=<id>`.
4. Server handles the request in a background thread and writes the response to the SSE stream as:
   ```text
   data: {"jsonrpc":"2.0","id":1,"result":{...}}
   ```

### JSON-RPC methods

| Method | Params | Description |
|--------|--------|-------------|
| `initialize` | — | Returns protocol version, capabilities, and server info. |
| `initialized` | — | Notification (no response). |
| `tools/list` | — | Returns the list of available tools. |
| `tools/call` | `name`, `arguments` | Executes a tool. |
| `resources/list` | — | Returns the list of available resources. |
| `resources/read` | `uri` | Reads a resource by URI. |
| `prompts/list` | — | Returns an empty list (no prompts implemented). |

### Capabilities

```json
{
  "tools": {},
  "resources": {}
}
```

### Tools schema

#### `shell`

Run a shell command on the Android box.

```json
{
  "name": "shell",
  "description": "Run a shell command on the Android box. Set root=true for system-level operations.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "command": {"type": "string", "description": "Shell command to run"},
      "timeout": {"type": "integer", "description": "Timeout in seconds"},
      "root": {"type": "boolean", "description": "Run as root via su (device must be rooted)"}
    },
    "required": ["command"]
  }
}
```

#### `list_packages`

List installed Android packages.

```json
{
  "name": "list_packages",
  "description": "List installed Android packages",
  "inputSchema": {
    "type": "object",
    "properties": {
      "filter": {"type": "string", "description": "Optional filter substring"}
    }
  }
}
```

#### `get_logcat`

Get recent Android logcat entries.

```json
{
  "name": "get_logcat",
  "description": "Get recent Android logcat entries",
  "inputSchema": {
    "type": "object",
    "properties": {
      "lines": {"type": "integer", "description": "Number of lines (max 500)"},
      "filter": {"type": "string", "description": "Optional grep filter"}
    }
  }
}
```

#### `get_storage`

Get storage usage information.

```json
{
  "name": "get_storage",
  "description": "Get storage usage information",
  "inputSchema": {"type": "object", "properties": {}}
}
```

#### `get_uptime`

Get system uptime and load.

```json
{
  "name": "get_uptime",
  "description": "Get system uptime and load",
  "inputSchema": {"type": "object", "properties": {}}
}
```

#### `reboot`

Reboot the Android box.

```json
{
  "name": "reboot",
  "description": "Reboot the Android box",
  "inputSchema": {"type": "object", "properties": {}}
}
```

### Resources schema

```json
{
  "device://info": {
    "name": "Device Info",
    "description": "Basic Android device information",
    "mimeType": "application/json"
  },
  "device://storage": {
    "name": "Storage Info",
    "description": "Storage usage summary",
    "mimeType": "application/json"
  }
}
```

### Tool result format

Each tool returns a JSON-RPC result containing:

```json
{
  "content": [
    {
      "type": "text",
      "text": "Return code: 0\n\nSTDOUT:\n...\n\nSTDERR:\n..."
    }
  ],
  "isError": false
}
```

### Root command execution

When `root=true`, the server wraps the command as:

```python
full_path = "/data/data/com.termux/files/usr/bin:/data/data/com.termux/files/usr/bin/applets:/system/bin:/vendor/bin:/system/xbin"
cmd = f"su 0 -c {shlex.quote(f'PATH={full_path}:$PATH; ' + cmd)}"
```

The `shlex.quote` safely escapes the inner command. The full `PATH` is prepended so system binaries (`wpa_cli`, `ifconfig`, `ping`, `svc`, etc.) are found.

### Example client code

```python
import json
import urllib.request
import threading
import time

BASE = "http://192.168.1.43:8080"
results = []

def listen():
    req = urllib.request.Request(f"{BASE}/sse")
    with urllib.request.urlopen(req, timeout=15) as r:
        sid = None
        for line in r:
            line = line.decode().strip()
            if line.startswith("event: endpoint"):
                data = next(r).decode().strip()
                if data.startswith("data: "):
                    sid = data[6:].split("session_id=")[1]
                    results.append(("sid", sid))
            elif line.startswith("data: "):
                results.append(("msg", json.loads(line[6:])))

threading.Thread(target=listen, daemon=True).start()
time.sleep(1)

sid = None
for t, v in results:
    if t == "sid":
        sid = v
        break

payload = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
        "name": "shell",
        "arguments": {
            "command": "wpa_cli -p /data/vendor/wifi/wpa/sockets -i wlan0 status | grep wpa_state",
            "root": True
        }
    }
}

urllib.request.urlopen(
    urllib.request.Request(
        f"{BASE}/message?session_id={sid}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST"
    ),
    timeout=10
)

time.sleep(2)
for t, v in results:
    if t == "msg" and v.get("id") == 1:
        print(v["result"]["content"][0]["text"])
```

### Known limitations

- The server does not close SSE connections gracefully; clients that disconnect may leave `CLOSE_WAIT` sockets on the server. This should be fixed for production use.
- No authentication is implemented. Do not expose the server beyond the local network.
- The `tools/call` handler returns a JSON-RPC response immediately but processes the request in a background thread; clients must correlate by `id`.
- Timeout is configurable per call but defaults to 30 seconds.

### Suggested MCP additions

To make the server more useful for this box:

- `wifi_status` — returns `wpa_cli status`, `ifconfig wlan0`, and route info.
- `wifi_connect` — runs `/data/local/tmp/wifi_manual.sh`.
- `wifi_disconnect` — kills `wpa_supplicant` and flushes the IP.
- `reboot_to_recovery` — reboots to recovery.
- `get_dmesg` — returns kernel log.
- `get_prop` / `set_prop` — read/write Android properties.
- `push_file` / `pull_file` — transfer files via base64.
- `adb_shell` — redundant with `shell`, but can enforce non-root context.

---

## Appendix — Compatible OS / BIOS / Firmware

This device is a **Rockchip RK3328** TV box (`rk3328_box`, device tree `rockchip,rk3328-box-liantong-avb`). It does not have a traditional BIOS. It boots from an **IDB (Identity Block) + U-Boot** stored on eMMC, and supports recovery via **Rockusb Mode** and **MaskROM Mode**.

### Alternative operating systems

| OS | Compatibility | Notes |
|----|---------------|-------|
| **Stock Android / custom Android ROMs** | High | Generic RK3328 firmware images exist for T9, A5X Max, MX10, H96 Max, Z28, T98. Most common flash method is `.img` via RKDevTool or SD card. |
| **Armbian (rk3318-box)** | Good | Official Armbian board target: `rk3318-box`. Offers Ubuntu 24.04 XFCE and Debian 13 Trixie minimal. Kernel 6.18.x. |
| **LibreELEC / CoreELEC** | Variable | Requires the correct DTB. Onboard WiFi often does not work; USB WiFi adapters commonly used. |
| **Mainline Linux / Debian / Ubuntu** | Variable | Firefly ROC-RK3328-CC docs cover `rkdeveloptool` and `upgrade_tool`. Device tree must match your board. |

### Flashing methods

| Method | Tool | When to use |
|--------|------|-------------|
| **SD card boot** | `SD_Firmware_Tool.exe`, BalenaEtcher, `dd` | Safest first attempt; reversible by removing the SD card. |
| **USB cable flash** | **RKDevTool**, **RK Batch Tool**, **FactoryTool** (Windows) | Full eMMC flash; requires Rockchip USB drivers. |
| **Linux command line** | `rkdeveloptool`, `upgrade_tool` | Flash from Linux host. |
| **MaskROM mode** | Any Rockchip tool | Last resort when bootloader is damaged. Requires shorting eMMC CLK to GND briefly while powering on. |

### Important caveats

- **Device tree is the critical factor.** The firmware must include a DTB that matches your board's WiFi, Ethernet, HDMI, audio, and USB layout.
- Your board's device tree is `rockchip,rk3328-box-liantong-avb` (also compatible with `rockchip,rk3328`).
- The closest official Armbian target is `rk3318-box`, which may work but may not initialize every peripheral perfectly.
- Flashing the wrong firmware can brick WiFi, Ethernet, or HDMI, and may require MaskROM mode to recover.

### Armbian vs Ubuntu desktop PC

Armbian will feel similar to Ubuntu/Debian in many ways, but it will **not** be identical to a regular x86 Ubuntu desktop PC. Important differences:

| Area | Armbian on RK3328 | Typical Ubuntu desktop PC |
|------|-------------------|---------------------------|
| **Architecture** | ARM64 (`aarch64`) | x86-64 (`amd64`) |
| **Package availability** | Most packages work, but some proprietary or x86-only apps do not (e.g., Chrome, certain games, some Docker images). | Full x86 package ecosystem. |
| **GPU / graphics** | Mali-450 MP2 with open-source `lima` driver. Desktop compositing works, but gaming and heavy 3D are limited. | NVIDIA/AMD/Intel drivers with full 3D acceleration. |
| **Video decoding** | Hardware decode for H.264/H.265/VP9 may work under Android, but in Linux it often depends on `ffmpeg` patches and `v4l2-request`. Not as plug-and-play. | Desktop CPUs/GPUs handle decode easily; drivers mature. |
| **WiFi** | Broadcom `bcmdhd` module. Armbian may not include the exact firmware or DTB binding for your board, so WiFi may not work out of the box. | Usually works with standard kernel drivers. |
| **Ethernet** | Rockchip `rk_gmac-dwmac` driver is usually well supported in mainline. | Intel/Realtek drivers, very stable. |
| **Bluetooth** | Your board reports `config.disable_bluetooth=true`; likely not usable in Linux either. | Standard USB/PCIe Bluetooth works. |
| **Audio** | HDMI audio and analog AV may need DTB/DAC configuration. | Usually works automatically. |
| **Performance** | 4x Cortex-A53 @ ~1.5 GHz, 4 GB RAM. Good for light server/HTPC tasks, slow for heavy browsing or compilation. | Desktop CPUs are much faster. |
| **Boot** | Boots from eMMC or SD card; no UEFI/GRUB in the traditional sense. | UEFI + GRUB bootloader. |
| **GPIO / I/O** | Some RK3328 boxes expose UART pads; GPIO headers may be limited. | Full PCIe, USB, GPIO on SBCs or motherboards. |

### Verdict

- **For a headless server or lightweight Linux use:** Armbian is a good choice. Ethernet is likely to work; WiFi may require extra work.
- **For a desktop replacement:** It will not match an x86 Ubuntu PC. Browsing, video calls, and heavy multitasking will be sluggish.
- **For media center:** LibreELEC/CoreELEC is purpose-built for this; Armbian with Kodi is possible but less optimized.
- **For keeping the existing Android experience:** A clean stock/custom Android ROM is the simplest option.

## Appendix — Bluetooth Status

**Bluetooth is already enabled and working on the Android box.** The property `config.disable_bluetooth=true` is misleading — it only disables the UI toggle, not the Bluetooth adapter.

### Current state

```bash
adb shell 'dumpsys bluetooth_manager | grep -E "enabled|state|address|name"'
```

Output shows:

- **enabled:** `true`
- **state:** `ON`
- **address:** `22:22:9E:65:01:00`
- **name:** `TONY-TV`
- **bonded device:** `TONY-XS` (`38:53:9C:AC:FB:30`)

### How to enable/toggle via command line

```bash
# Check if Bluetooth is enabled globally
adb shell 'settings get global bluetooth_on'

# Enable Bluetooth
adb shell 'su -c "settings put global bluetooth_on 1"'

# Toggle adapter via service call
adb shell 'su -c "service call bluetooth_manager 5"'

# Open Bluetooth settings via intent
adb shell 'su -c "am start -a android.settings.BLUETOOTH_SETTINGS"'
```

### Why the Settings UI may not show Bluetooth

- The build property `config.disable_bluetooth=true` removes the Bluetooth toggle from the stock Android Settings UI.
- The Bluetooth service itself (`vendor.bluetooth-1-0`) is running and the adapter is ON.
- Use ADB commands or a third-party app with `BLUETOOTH` permission to manage Bluetooth.

### Bluetooth under Armbian / Linux

- If the Bluetooth module is attached to the same Broadcom combo chip as WiFi (`bcmdhd`), it may share firmware or require `hci_uart` / `btattach` setup.
- Linux support depends on whether the DTB exposes the Bluetooth UART and provides the correct firmware (`BCM*.hcd`).
- This has not been tested yet.

## Appendix — Advantages of Armbian/Linux Over Current Android

Moving from the current Android build to Armbian/Linux on this RK3328 box would bring several advantages, depending on what you want to use the box for.

### 1. Full root control without Android restrictions

- On Android, even with `su` root, many system operations are guarded by SELinux, the Android framework, and vendor partitions.
- On Armbian, you get a standard Linux root environment with `sudo` and full `systemd`/`sysfs` access.

### 2. Standard package manager (`apt`)

- Install software directly: `apt install nginx`, `python3`, `node`, `docker.io`, `kodi`, etc.
- No need to sideload APKs or compile Android binaries.

### 3. Better for server / headless / automation tasks

- Run a 24/7 home server: `home-assistant`, `pihole`, `jellyfin`, `samba`, `plex` (if performance allows).
- Cron jobs, systemd services, and background daemons are straightforward.
- No Android background process killing or Doze mode interfering.

### 4. No Android bloatware or telemetry

- The current Android build may include Chinese-market apps, analytics, or ad frameworks.
- Armbian is a minimal Debian/Ubuntu image; only what you install runs.

### 5. Better networking and firewall control

- Full `iptables`/`nftables`, `NetworkManager`, `systemd-networkd`, `hostapd`, `dnsmasq`, `openvpn`/`wireguard`.
- Easier to configure WiFi, Ethernet, routing, VPN, and static IPs without fighting Android's HAL.

### 6. SSH and remote management

- OpenSSH server out of the box (or `apt install openssh-server`).
- No dependency on ADB or the MCP server for remote shell access.

### 7. Cleaner development environment

- Standard Python, Node.js, Go, Rust toolchains via `apt` or official ARM64 builds.
- Easier to compile and run software from source.

### 8. Long-term updates

- Armbian receives kernel and package updates via `apt update && apt upgrade`.
- The current Android build is stuck on security patch `2020-05-05` with no official updates.

### 9. Better control over storage and partitions

- Access the full `/data` partition as a standard Linux filesystem.
- Easier to mount external drives, set up NFS/SMB shares, or run a NAS.

### 10. No Google Play Services dependency

- Useful if you want a privacy-focused or offline device.
- No need for a Google account or GMS framework.

### 11. Easier to run containers

- Docker works on ARM64 with some limitations on certain images.
- Good for isolating services.

### 12. Mainline kernel support

- Armbian uses a recent mainline kernel (`6.18.x`), which means better upstream drivers, security fixes, and hardware support over time.

### When to stay on Android

- You need the Android TV UI, DRM apps (Netflix, Disney+, Prime Video), or Android-specific apps.
- You want a plug-and-play media experience with existing remotes.
- Hardware features (like the current WiFi workaround) are easier to keep working on the existing Android firmware.

### Summary

| Use case | Android | Armbian/Linux |
|----------|---------|---------------|
| Media/TV apps | Good | Limited DRM support |
| Home server / NAS | Poor | Good |
| Development | Mediocre | Good |
| Privacy/Minimalism | Poor | Good |
| Updates | Stuck in 2020 | Active |
| Remote SSH | Requires MCP/ADB | Native |
| Package ecosystem | Play Store only | `apt` universe |
| Root control | Restricted | Full |

## Appendix — Backup & Rollback Procedure

Before trying Armbian or any alternative firmware, the critical Android partitions and user data were backed up.

### What was backed up

#### Critical system partitions (`/data/backup_critical/`)

| Partition | Size | Purpose |
|-----------|------|---------|
| `uboot.img` | 4 MB | Primary bootloader / IDB |
| `trust.img` | 4 MB | ARM Trusted Firmware |
| `security.img` | 4 MB | Security partition |
| `misc.img` | 4 MB | Misc bootloader data |
| `dtb.img` | 4 MB | Device tree blob |
| `dtbo.img` | 4 MB | Device tree overlay |
| `vbmeta.img` | 1 MB | Verified Boot metadata |
| `boot.img` | 64 MB | Android kernel + ramdisk |
| `recovery.img` | 96 MB | Recovery image |
| `backup.img` | 112 MB | Vendor backup partition |
| `cache.img` | 384 MB | Android cache |
| `metadata.img` | 16 MB | Metadata |
| `frp.img` | 512 KB | Factory Reset Protection |
| `baseparameter.img` | 1 MB | Base parameters |
| `logo.img` | 16 MB | Boot logo |
| `super.img` | 3.0 GB | APEX/system/vendor dynamic partition |

Total: **~1.8 GB** (fits in `/data`).

All images have MD5 checksums verified in `/data/backup_critical/checksums.md5`.

#### User data files (`/data/backup_data/`)

| File | Contents |
|------|----------|
| `termux_home.tar.gz` | `/data/data/com.termux/files/home` (MCP server, scripts) |
| `termux_shortcuts.tar.gz` | Termux:Widget shortcuts (empty if none) |
| `wifi_manual.sh` | Manual WiFi setup script |
| `wpa_supplicant_manual.conf` | Manual wpa_supplicant config |
| `WifiConfigStore.xml` | Android WiFi config store |
| `installed_packages.txt` | List of installed packages |
| `build_props.txt` | Full `getprop` dump for reference |

### What was NOT backed up

- The full **userdata partition** (`/dev/block/mmcblk1p17`, 55.6 GB raw) was not backed up because it is too large for `/data`.
- If you want a **complete byte-for-byte rollback**, you need an external USB drive (≥64 GB) to dump the entire `mmcblk1` image.

### Backup script

File: `/data/local/tmp/backup_android_box.sh`

```bash
#!/system/bin/sh
BACKUP_DIR=/data/backup_critical
DATA_BACKUP=/data/backup_data
LOG=/data/backup_critical.log

mkdir -p "$BACKUP_DIR" "$DATA_BACKUP"
exec > "$LOG" 2>&1

echo "=== Android Box Backup Started: $(date) ==="

for part in uboot trust security misc dtb dtbo vbmeta boot recovery backup cache metadata frp baseparameter logo super; do
    src="/dev/block/platform/ff520000.dwmmc/by-name/$part"
    if [ -L "$src" ]; then
        dst="$BACKUP_DIR/${part}.img"
        echo "[*] Backing up $src -> $dst"
        dd if="$src" of="$dst" bs=1M
        sync
    fi
done

cd "$BACKUP_DIR"
md5sum *.img > checksums.md5
sync

# User data files
tar -czf "$DATA_BACKUP/termux_home.tar.gz" -C /data/data/com.termux/files home
tar -czf "$DATA_BACKUP/termux_shortcuts.tar.gz" -C /data/data/com.termux/files .shortcuts
cp -r /data/local/tmp/wifi_manual.sh "$DATA_BACKUP/"
cp -r /data/vendor/wifi/wpa/wpa_supplicant_manual.conf "$DATA_BACKUP/"
cp -r /data/misc/wifi/WifiConfigStore.xml "$DATA_BACKUP/"
pm list packages > "$DATA_BACKUP/installed_packages.txt"
getprop > "$DATA_BACKUP/build_props.txt"

echo "=== Backup Finished: $(date) ==="
```

### How to restore (rollback)

If you flash Armbian to eMMC and want to return to the current Android build, run these commands from Android recovery or a rooted Android shell:

```bash
# Boot into a rooted Android shell or recovery with adb root
adb root
adb remount

# Restore critical partitions
for part in uboot trust security misc dtb dtbo vbmeta boot recovery backup cache metadata frp baseparameter logo super; do
    img="/data/backup_critical/${part}.img"
    dst="/dev/block/platform/ff520000.dwmmc/by-name/$part"
    if [ -f "$img" ] && [ -L "$dst" ]; then
        echo "[*] Restoring $part"
        dd if="$img" of="$dst" bs=1M
    fi
done

# Clear cache to avoid boot issues
echo "[*] Clearing cache"
make_ext4fs /dev/block/platform/ff520000.dwmmc/by-name/cache

# Reboot
reboot
```

**Note:** If `/data` was overwritten or erased by Armbian, the backup files will be gone. Store the backups on an external USB drive or PC before installing Armbian to eMMC.

### Full eMMC backup (optional, requires external storage)

If you want a complete byte-for-byte rollback image:

```bash
# Connect a USB drive (≥64 GB) and identify it (e.g., /dev/block/sda1)
mount /dev/block/sda1 /mnt/usb

# Dump entire eMMC (this will take a long time)
dd if=/dev/block/mmcblk1 of=/mnt/usb/mmcblk1_full_backup.img bs=1M
sync

# Or compress on the fly (even slower but smaller)
dd if=/dev/block/mmcblk1 bs=1M | gzip -c > /mnt/usb/mmcblk1_full_backup.img.gz
```

### Rollback from full eMMC image

```bash
# Boot into MaskROM or Rockusb mode
# Use rkdeveloptool or RKDevTool to flash the full image
rkdeveloptool db rk3328_loader.bin
rkdeveloptool wl 0 /mnt/usb/mmcblk1_full_backup.img
rkdeveloptool rd
```

Or from a rooted Android shell:

```bash
# WARNING: this overwrites everything on the eMMC
dd if=/mnt/usb/mmcblk1_full_backup.img of=/dev/block/mmcblk1 bs=1M
sync
reboot
```

## Appendix — Booting Armbian from SD Card

The safest way to try Armbian on this box is to **boot it from an SD card** without touching the eMMC. Remove the SD card to boot back into Android.

### Image used

- **Board target:** `rk3318-box` (compatible with RK3328 TV boxes)
- **Image:** `Armbian_community_26.8.0-trunk.170_Rk3318-box_resolute_current_6.18.35_xfce_desktop.img`
- **Size:** 1.3 GB extracted, 812 MB compressed (`.xz`)
- **Download URL:** `https://dl.armbian.com/rk3318-box/Resolute_current_xfce`
- **SHA256:** `1a579a248eba85040358f52eb9575841a27279f6e62bb208fec90b09dbe981d6`

### How to write the image to SD card

**Option 1 — Write from this PC (I can do it for you)**

1. Insert a microSD card (≥8 GB, Class 10 or faster) into your PC.
2. Tell me the device path (e.g., `/dev/sdX` on Linux, `/dev/diskN` on macOS, or a drive letter on Windows).
3. I will run `dd` or `BalenaEtcher` to flash the image.

**Option 2 — Write it yourself**

**Linux/macOS:**

```bash
# Identify the SD card (e.g., /dev/sdX). BE CAREFUL — do not pick your system disk.
lsblk

# Unmount any partitions on the SD card
sudo umount /dev/sdX* 2>/dev/null

# Flash the image (replace /dev/sdX with your SD card)
sudo dd if=rk3318-box_resolute_xfce.img of=/dev/sdX bs=4M status=progress conv=fsync

# Or use the compressed image directly
xzcat rk3318-box_resolute_xfce.img.xz | sudo dd of=/dev/sdX bs=4M status=progress conv=fsync
```

**Windows:** use [BalenaEtcher](https://www.balena.io/etcher/) or [Rufus](https://rufus.ie/) to flash the `.img` file.

### How to boot from SD card

1. **Power off the Android box.**
2. **Insert the prepared microSD card** into the box's SD card slot.
3. **Hold the reset button** while powering on:
   - The reset button is usually a small pinhole inside the **AV port** or on the side/back of the box.
   - Use a toothpick or paperclip to press it.
   - Keep it pressed for 5–10 seconds after power-on.
4. **Release the button.** The box should boot from the SD card into Armbian.

### If it does not boot from SD card automatically

Some RK3328/RK3318 TV boxes are configured to boot from eMMC first. Try these methods:

- **Method A:** Hold the reset button for 15–20 seconds while powering on.
- **Method B:** Boot the box into **MaskROM Mode** (short eMMC CLK to GND briefly while powering on), then use `rkdeveloptool` or `RKDevTool` to load the SD card bootloader.
- **Method C:** Use a specially prepared SD card that includes the **idbloader** at the right offset. Armbian images usually include this.

### What to expect on first boot

- Armbian will resize the root partition to fill the SD card on first boot.
- You will be asked to create a root password and set up a user account.
- Default login after resize is usually `root` with a generated password, or you may need to use a serial console.
- Check the Armbian documentation for the exact first-boot steps for this image.

### How to return to Android

- **Power off the box.**
- **Remove the SD card.**
- **Power on.** The box will boot back into the original Android eMMC installation.

### If you want to install Armbian to eMMC

Only do this after you have tested the SD card boot and are satisfied. Installation to eMMC will erase Android. Use `armbian-install` or `nand-sata-install` from within the running Armbian SD card.

## Related Files

- `/home/tony/GoogleDrive/Tony AI/KB/Android Box/android-box-wifi-and-mcp.md` — high-level KB note with hardware info.
