---
category: operations
---

# Key Commands Reference

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

