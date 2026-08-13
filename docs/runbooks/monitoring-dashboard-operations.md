---
title: Monitoring Dashboard Operations Runbook
description: Operational procedures for the Chaba monitoring dashboard including real-time service monitoring, performance metrics, alert management, and troubleshooting
tags: [monitoring, dashboard, operations, runbook, metrics, alerts]
created: 2026-08-13
updated: 2026-08-13
category: operations
related: [scripts/monitoring-dashboard.mjs, ssot.infrastructure/ssot.health.yml, kb/health-check.md]
search_keywords: [monitoring, dashboard, metrics, alerts, service-health, performance]
---

# Monitoring Dashboard Operations Runbook

**Abstract**: Complete operational guide for the Chaba monitoring dashboard including real-time service status monitoring, performance metrics visualization, alert history, backup monitoring, GPU tracking, and troubleshooting procedures.

## Overview

The Chaba monitoring dashboard provides real-time visibility into infrastructure health with automated service checks, performance metrics monitoring, alert history tracking, and backup system monitoring. It includes a web interface, JSON API endpoints, and systemd automation for continuous monitoring.

## Purpose

- **Real-time Monitoring**: 30-second auto-refresh of service status and metrics
- **Performance Tracking**: Memory, disk, GPU, and network performance monitoring
- **Alert Management**: Recent alerts from health monitor with severity levels
- **Backup Monitoring**: Google Drive mount status and backup health tracking
- **API Integration**: JSON endpoints for external monitoring tools
- **Systemd Automation**: Automated service startup and monitoring

## Key Files

| File | Purpose |
|------|---------|
| `scripts/monitoring-dashboard.mjs` | Main monitoring dashboard server |
| `scripts/test-monitoring-dashboard.sh` | Dashboard test suite |
| `systemd/chaba-monitoring-dashboard.service` | Systemd service for auto-start |
| `logs/health-monitor.log` | Health monitor alert source |
| `/var/log/chaba-backup.log` | Backup operation logs |

## Dashboard Architecture

### Web Interface
- **URL**: `http://localhost:3002`
- **Auto-refresh**: 30 seconds
- **Manual refresh**: Refresh button
- **Dark theme**: Modern dark interface

### API Endpoints
- **`/`**: Main dashboard HTML
- **`/api/status`**: JSON API with all metrics
- **`/api/refresh`**: Force refresh endpoint

### Monitored Components
1. **Services**: status-api, yomi-api, caddy, trade-api
2. **Containers**: postgres, redis, caddy, gpu-queue
3. **Performance**: Memory, disk, GPU temperature, GPU utilization
4. **Backup**: Google Drive mount, backup status, backup count
5. **Alerts**: Recent alerts from health monitor

## Operational Procedures

### Dashboard Startup

**Manual Startup**:
```bash
# Start dashboard manually
node /home/tony/CascadeProjects/chaba/scripts/monitoring-dashboard.mjs
```

**Systemd Automation**:
```bash
# Enable auto-start on boot
systemctl --user enable chaba-monitoring-dashboard.service

# Start dashboard service
systemctl --user start chaba-monitoring-dashboard.service

# Check service status
systemctl --user status chaba-monitoring-dashboard.service
```

**Access Dashboard**:
- Open browser to `http://localhost:3002`
- Dashboard auto-refreshes every 30 seconds
- Manual refresh with Refresh button

### API Usage

**Get Current Status**:
```bash
# Get JSON status
curl http://localhost:3002/api/status

# Get specific metrics
curl http://localhost:3002/api/status | jq '.services'
curl http://localhost:3002/api/status | jq '.performance'
curl http://localhost:3002/api/status | jq '.backup'
curl http://localhost:3002/api/status | jq '.gpu'
```

**Force Refresh**:
```bash
# Trigger immediate dashboard update
curl http://localhost:3002/api/refresh
```

### Testing and Validation

**Run Dashboard Tests**:
```bash
./scripts/test-monitoring-dashboard.sh
```

**Test Coverage**:
- Script existence and permissions
- Node.js availability
- Systemd service file validation
- Dashboard startup and accessibility
- API endpoint functionality

### Health Check Integration

The dashboard integrates with the existing health monitor system:
- **Alert Source**: `/home/tony/CascadeProjects/chaba/logs/health-monitor.log`
- **Alert Types**: Critical, warning, info
- **Alert Display**: Recent 20 alerts with severity color-coding
- **Alert Details**: Timestamp, severity, message, source

## Troubleshooting

### Issue: Dashboard Not Accessible

**Symptoms**:
- Browser cannot connect to `http://localhost:3002`
- Connection refused error
- Dashboard not responding

**Causes**:
- Dashboard service not running
- Port 3002 already in use
- Node.js not available
- Network connectivity issues

**Solutions**:
```bash
# Check if dashboard is running
ps aux | grep monitoring-dashboard

# Check port availability
lsof -i :3002

# Start dashboard manually
node /home/tony/CascadeProjects/chaba/scripts/monitoring-dashboard.mjs

# Check systemd service status
systemctl --user status chaba-monitoring-dashboard.service

# Restart systemd service
systemctl --user restart chaba-monitoring-dashboard.service
```

### Issue: Service Status Not Updating

**Symptoms**:
- Service status shows stale information
- Last update timestamp old
- Auto-refresh not working

**Causes**:
- Dashboard update loop stopped
- Service health check failures
- Network connectivity issues

**Solutions**:
```bash
# Force refresh via API
curl http://localhost:3002/api/refresh

# Check dashboard logs
tail -f /var/log/chaba-monitoring-dashboard.log

# Restart dashboard
systemctl --user restart chaba-monitoring-dashboard.service

# Test service health manually
curl -f http://tony-omen.local:8080/api/health
curl -f http://tony-omen.local:8080/
```

### Issue: GPU Metrics Not Showing

**Symptoms**:
- GPU temperature shows "N/A"
- GPU utilization not updating
- GPU memory shows "N/A"

**Causes**:
- nvidia-smi not available
- GPU not detected
- NVIDIA drivers not loaded

**Solutions**:
```bash
# Check nvidia-smi availability
nvidia-smi

# Check GPU status
nvidia-smi --query-gpu=name,memory.used,memory.total,temperature.gpu,utilization.gpu --format=csv

# Check NVIDIA drivers
nvidia-smi --driver-version

# Restart dashboard to retry GPU detection
systemctl --user restart chaba-monitoring-dashboard.service
```

### Issue: Backup Status Not Updating

**Symptoms**:
- Backup status shows "unknown"
- Google Drive mount status incorrect
- Backup count not updating

**Causes**:
- Google Drive not mounted
- Backup logs not accessible
- Backup directory structure changed

**Solutions**:
```bash
# Check Google Drive mount
mount | grep gdrive

# Check backup directory
ls -la "/home/tony/GoogleDrive/Tony AI/backup/chaba/daily"

# Check backup logs
tail -f /var/log/chaba-backup.log

# Test backup monitor
./scripts/backup-monitor.sh all
```

### Issue: High Memory Usage in Dashboard

**Symptoms**:
- Dashboard process using excessive memory
- Memory leak suspected
- System resources degraded

**Causes**:
- Memory leak in dashboard code
- Excessive data retention
- Update interval too frequent

**Solutions**:
```bash
# Check dashboard memory usage
ps aux | grep monitoring-dashboard

# Restart dashboard to clear memory
systemctl --user restart chaba-monitoring-dashboard.service

# Monitor memory usage over time
watch -n 5 'ps aux | grep monitoring-dashboard'

# Consider adjusting UPDATE_INTERVAL in monitoring-dashboard.mjs
```

## Performance Metrics

**Dashboard Performance**:
- Memory usage: ~50-100MB
- CPU usage: <5% during updates
- Update interval: 30 seconds
- API response time: <100ms

**Monitoring Coverage**:
- Services: 4 HTTP endpoints + 4 Docker containers
- Performance: Memory, disk, GPU metrics
- Alerts: Last 20 alerts from health monitor
- Backup: Mount status, last backup, backup count

**System Impact**:
- Minimal CPU usage during updates
- Low memory footprint
- Network usage: ~1-2KB per update
- Storage: Logs only (~1MB/day)

## Related Documentation

- **Health Check**: `docs/kb/health-check.md` - Health monitor configuration
- **SSOT Health**: `docs/ssot/infrastructure/ssot.health.yml` - Service health configuration
- **System Automation**: `docs/kb/system-automation.md` - Systemd timer management

## Change History

| Date | Change | Author |
|------|--------|--------|
| 2026-08-13 | Initial creation with real-time monitoring and API endpoints | Devin |