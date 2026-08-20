---
category: operations
---

# Systemd Automation

### Backup Service
**File:** `/etc/systemd/system/chaba-backup.service`
```ini
[Unit]
Description=Chaba Infrastructure Backup System
After=network.target docker.service

[Service]
Type=oneshot
User=tony
WorkingDirectory=/home/tony/CascadeProjects/chaba
ExecStart=/home/tony/CascadeProjects/chaba/scripts/backup-manager.sh
StandardOutput=append:/var/log/chaba-backup.log
StandardError=append:/var/log/chaba-backup.log
```

### Backup Timer
**File:** `/etc/systemd/system/chaba-backup.timer`
```ini
[Unit]
Description=Chaba Infrastructure Backup Timer (Daily at 2 AM)

[Timer]
OnCalendar=*-*-* 02:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

### Monitoring Service
**File:** `/etc/systemd/system/chaba-backup-monitor.service`
```ini
[Unit]
Description=Chaba Backup Monitoring and Alerting
After=network.target

[Service]
Type=oneshot
User=tony
WorkingDirectory=/home/tony/CascadeProjects/chaba
ExecStart=/home/tony/CascadeProjects/chaba/scripts/backup-monitor.sh
StandardOutput=append:/var/log/chaba-backup-monitor.log
StandardError=append:/var/log/chaba-backup-monitor.log
```

### Monitoring Timer
**File:** `/etc/systemd/system/chaba-backup-monitor.timer`
```ini
[Unit]
Description=Chaba Backup Monitoring Timer (Hourly)

[Timer]
OnCalendar=hourly
Persistent=true

[Install]
WantedBy=timers.target
```

## Script Updates

### Backup Manager Changes
- Updated `BACKUP_ROOT` to Google Drive path
- Added FUSE compatibility layer for Docker operations
- Fixed `verification_failed` variable scope issue
- Updated backup counting to use `find` commands for subdirectory structure

### Backup Monitor Changes
- Updated all `ls -t` commands to `find` with `sort -r`
- Adjusted `MIN_BACKUP_SIZE_MB` from 10 to 1 (for small database)
- Fixed backup failure check to use proper date filtering
- Fixed arithmetic operations (removed `(( ))` conflicts)
- Updated backup completeness check to detect subdirectory backups

### Health Monitor Integration
**File:** `scripts/health-monitor.sh`
```bash
# Google Drive backup mount check
if ! mount | grep -q "gdrive.*on /home/tony/GoogleDrive"; then
    alert critical "Google Drive Not Mounted" "Backup storage unavailable — remount with: rclone mount gdrive: /home/tony/GoogleDrive --daemon"
fi

# Backup directory accessibility
if [[ -d "/home/tony/GoogleDrive/Tony AI/backup/chaba" ]]; then
    if ! touch "/home/tony/GoogleDrive/Tony AI/backup/chaba/.health-check" 2>/dev/null; then
        alert critical "Google Drive Not Writable" "Backup directory not writable — check mount and permissions"
    else
        rm -f "/home/tony/GoogleDrive/Tony AI/backup/chaba/.health-check" 2>/dev/null
    fi
fi
```

## Monitoring and Alerting

### Backup Monitoring Checks
1. **Freshness:** Latest backup age < 36 hours
2. **Size:** Latest backup > 1MB (adjusted for small database)
3. **Integrity:** gzip/tar verification
4. **Completeness:** All backup types present
5. **Rotation:** Proper retention policy enforcement
6. **Failures:** Recent backup failures < 3 in 24 hours
7. **Disk Space:** > 5GB available, < 90% used

### Alert Thresholds
```bash
MAX_BACKUP_AGE_HOURS=36
MIN_BACKUP_SIZE_MB=1  # Adjusted for small database
MAX_FAILURE_COUNT=3
```

### Log Files
- **Backup Log:** `/var/log/chaba-backup.log`
- **Monitor Log:** `/var/log/chaba-backup-monitor.log`
- **Alert Log:** `/var/log/chaba-backup-alerts.log`

## Troubleshooting

### Google Drive Mount Issues
**Problem:** Google Drive not mounted
```bash
# Check mount status
mount | grep gdrive

# Remount Google Drive
rclone mount gdrive: /home/tony/GoogleDrive --daemon

# Check rclone status
rclone status gdrive
```

### Backup Permission Issues
**Problem:** Permission denied writing to Google Drive
```bash
# Fix log file ownership
sudo chown tony:tony /var/log/chaba-backup.log
sudo chown tony:tony /var/log/chaba-backup-monitor.log
sudo chown tony:tony /var/log/chaba-backup-alerts.log
```

### Docker Volume Backup Failures
**Problem:** Docker cannot create mount source path
**Solution:** Ensure FUSE compatibility layer is working (local temp directory → Google Drive copy)

### Backup Monitoring Issues
**Problem:** Monitoring script fails with integer comparison errors
**Solution:** Ensure proper date filtering and arithmetic operations in backup-monitor.sh

## Performance

### Backup Runtime
- **Full Backup:** 21-22 seconds
- **Database Backup:** ~1 second
- **Volume Backups:** ~2 seconds (3 volumes)
- **Configuration Backups:** ~3 seconds
- **Documentation Backup:** ~2 seconds

### Storage Usage
- **Initial:** 463M total (3 daily backup sets)
- **Growth Rate:** ~150MB per day (expected)
- **Google Drive Sync:** Automatic via rclone

## SSOT Integration

### Automation Configuration
**File:** `docs/ssot/infrastructure/ssot.automation.yml`
- Version 7 includes complete backup system configuration
- Backup types, retention policies, monitoring details documented
- Systemd services and restoration features listed

### Health Configuration
**File:** `docs/ssot/infrastructure/ssot.health.yml`
- gdrive-backup service added as optional system service
- Verification procedures for Google Drive mount
- Recovery actions for mount issues

