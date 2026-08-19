---
category: system
---

# System Automation
## What it is

Automated monitoring and maintenance scripts for Chaba infrastructure.


Automated monitoring and maintenance scripts for Chaba infrastructure.
## Context/Background

Created 2026-08-06 as part of Chaba infrastructure documentation.


## Scripts

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

## Setup Instructions

1. **Make scripts executable:**
```bash
chmod +x scripts/*.mjs scripts/*.sh
```

2. **Set up automation:**
```bash
bash scripts/setup-automation.sh
```

3. **Verify installation:**
```bash
# Test GPU monitoring
node scripts/gpu-monitor.mjs

# Test system maintenance
node scripts/system-maintenance.mjs

# View dashboard
node scripts/monitoring-dashboard.mjs
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

## Data Retention

- **GPU Logs**: Retained indefinitely (consider periodic cleanup)
- **Alert Logs**: Retained indefinitely (consider periodic cleanup)
- **Maintenance Logs**: Retained indefinitely
- **System Logs**: Cleaned automatically (>30 days)

## Customization

### Adjust Thresholds
Edit `scripts/gpu-monitor.mjs`:
```javascript
const THRESHOLDS = {
  warning: 80,    // VRAM warning threshold
  critical: 90,  // VRAM critical threshold
  temp_warning: 75,  // Temperature warning
  temp_critical: 85  // Temperature critical
};
```

### Modify Schedule
Edit `scripts/setup-automation.sh` cron expressions.

### Add Maintenance Tasks
Edit `scripts/system-maintenance.mjs` to add new functions.

## Integration

### Overnight Assessment
The system maintenance script integrates with the overnight assessment for comprehensive health monitoring.

### GPU Queue
GPU monitoring can be integrated with GPU queue management for intelligent resource allocation.

### Status API
Monitoring data can be exposed via the status API for web dashboard integration.

## Best Practices

1. **Regular Monitoring**: Review dashboard output weekly
2. **Alert Response**: Investigate critical alerts immediately
3. **Disk Management**: Monitor disk usage trends monthly
4. **Backup Strategy**: Ensure backups before major cleanup operations
5. **Testing**: Test automation scripts in development before production deployment

## Performance Impact

- **GPU Monitoring**: Minimal overhead (<1 second per check)
- **System Maintenance**: Variable (1-5 minutes depending on cleanup needed)
- **Dashboard**: Minimal overhead (<1 second)

## Security Considerations

- Scripts require appropriate system permissions
- Docker operations need Docker daemon access
- Journal cleanup requires sudo privileges
- Log files should be protected from unauthorized access

## Future Enhancements

- [ ] Web-based monitoring dashboard
- [ ] Email/SMS alert notifications
- [ ] Predictive maintenance using historical data
- [ ] Integration with monitoring services (Prometheus, Grafana)
- [ ] Automated remediation for common issues
- [ ] Resource usage forecasting
## Tags

- **docker**: docker
- **containers**: containers
- **containerization**: containerization
- **gpu**: gpu
- **nvidia**: nvidia
- **cuda**: cuda
- **ml**: ml
- **ai**: ai
- **api**: api
- **rest**: rest
- **http**: http
- **web**: web
- **monitoring**: monitoring
- **health**: health
- **metrics**: metrics
- **logging**: logging
- **security**: security
- **auth**: auth
- **encryption**: encryption
- **ssl**: ssl
- **deployment**: deployment
- **ci**: ci
- **cd**: cd
- **performance**: performance
- **optimization**: optimization
- **caching**: caching
- **testing**: testing
- **e2e**: e2e
- **automation**: automation
- **documentation**: documentation
- **kb**: kb
- **knowledge-base**: knowledge-base
- **2026**: 2026
