---
category: operations
---

# Systemd Timers

Yomi uses systemd timers for automated operation:

### API Server (`yomi-api.service`)
- **Purpose**: HTTP API server for Yomi data
- **Location**: `/etc/systemd/system/yomi-api.service`
- **Enabled**: Yes (auto-restart on failure)
- **Status**: Active (added 2026-08-04)

### Fetch Timer (`yomi-fetch.timer`)
- **Frequency**: Every 30 minutes (`*:0/30`) (updated 2026-08-11 for intermittent PC usage)
- **Service**: `yomi-fetch.service`
- **Location**: `/etc/systemd/system/yomi-fetch.timer`
- **Enabled**: Yes (symlinked in `timers.target.wants`)
- **Skip Logic**: Skips fetch if last successful fetch was within 30 minutes (configurable via `YOMI_FETCH_SKIP_MINUTES`)
- **Boot Service**: `yomi-fetch-on-boot.service` runs forced fetch on system boot if last fetch was too long ago

### Process Timer (`yomi-process.timer`)
- **Frequency**: Every hour during midnight to 7 AM, plus 12PM, 6PM, 8PM (`*-*-* 00,01,02,03,04,05,06,07,12,18,20:*:0/1`) (updated 2026-08-11 for intermittent PC usage)
- **Service**: `yomi-process.service`
- **Location**: `/etc/systemd/system/yomi-process.timer`
- **Enabled**: Yes (symlinked in `timers.target.wants`)
- **Skip Logic**: Skips processing if last successful processing was within 12 hours (configurable via `YOMI_PROCESS_SKIP_HOURS`)
- **Boot Service**: `yomi-process-on-boot.service` runs forced processing on system boot if last processing was too long ago
- **Flexible Scheduling**: Added daytime processing windows (12PM, 6PM, 8PM) to handle PC being off during overnight hours

### Management Commands
```bash
# Check timer status
systemctl list-timers yomi-*

# View timer logs
journalctl -u yomi-fetch.timer
journalctl -u yomi-process.timer
journalctl -u yomi-api.service

# Manual trigger
systemctl start yomi-fetch.service
systemctl start yomi-process.service
systemctl restart yomi-api.service
```

