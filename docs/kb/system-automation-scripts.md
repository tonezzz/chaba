---
category: operations
---

# Scripts

### GPU Monitoring (`scripts/gpu-monitor.mjs`)
Monitors GPU memory usage, utilization, and temperature with configurable thresholds.

**Features:**
- Real-time GPU status monitoring
- Configurable alert thresholds (VRAM, temperature)
- Historical data logging and statistics
- Alert logging for threshold violations

**Thresholds:**
- VRAM Warning: 80%
- VRAM Critical: 90%
- Temperature Warning: 75°C
- Temperature Critical: 85°C

**Usage:**
```bash
# Run manual check
node scripts/gpu-monitor.mjs

# Export JSON data
node scripts/gpu-monitor.mjs --export
```

**Data Location:**
- Logs: `data/gpu-monitor/gpu-usage.log`
- Alerts: `data/gpu-monitor/gpu-alerts.log`

### System Maintenance (`scripts/system-maintenance.mjs`)
Automated system cleanup and health checks.

**Tasks:**
- Docker cleanup (containers, images, volumes, build cache)
- Journal log cleanup (limit to 500M)
- System log cleanup (>30 days)
- Disk space monitoring
- Docker health check
- GPU monitoring integration

**Usage:**
```bash
# Run maintenance manually
node scripts/system-maintenance.mjs

# Export JSON report
node scripts/system-maintenance.mjs --export
```

**Logs:** `logs/maintenance/maintenance.log`

### Monitoring Dashboard (`scripts/monitoring-dashboard.mjs`)
Real-time dashboard for system health monitoring.

**Displays:**
- Current GPU status (VRAM, utilization, temperature)
- 24h historical statistics
- Recent alerts
- System health (disk, containers)

**Usage:**
```bash
node scripts/monitoring-dashboard.mjs
```

### Automation Setup (`scripts/setup-automation.sh`)
Sets up cron jobs for automated execution.

**Scheduled Tasks:**
- GPU Monitoring: Every 5 minutes
- System Maintenance: Daily at 3 AM
- Overnight Assessment: Daily at 2 AM

**Usage:**
```bash
bash scripts/setup-automation.sh
```

## Monitoring & Alerts

### GPU Alerts
Alerts are triggered when thresholds are exceeded:
- **VRAM Usage**: Monitors memory consumption
- **Temperature**: Monitors GPU thermal status
- **Utilization**: Tracks GPU load patterns

### System Health
- **Disk Space**: Monitors root partition usage
- **Docker Health**: Checks container status
- **Resource Trends**: Historical data analysis

## Troubleshooting

### GPU Monitoring Issues
- Ensure `nvidia-smi` is available
- Check GPU driver installation
- Verify NVIDIA GPU is accessible

### Automation Issues
- Check cron service status: `systemctl status cron`
- Review logs: `logs/automation/`
- Verify script permissions

### Maintenance Issues
- Docker daemon must be running
- Sufficient permissions for system cleanup
- Network access for Docker image operations

