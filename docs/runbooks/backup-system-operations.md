---
title: Backup System Operations Runbook
description: Comprehensive operational procedures for the Chaba backup system including Google Drive integration, automated backups, monitoring, and restoration
tags: [backup, operations, runbook, google-drive, disaster-recovery]
created: 2026-08-13
updated: 2026-08-13
category: operations
related: [ssot.infrastructure/ssot.automation.yml, ssot.infrastructure/ssot.health.yml, kb/google-drive-backup-system.md]
search_keywords: [backup, restore, google-drive, disaster-recovery, backup-manager, backup-monitor]
---

# Backup System Operations Runbook

**Abstract**: Complete operational guide for the Chaba backup system including automated daily backups to Google Drive, backup monitoring, restoration procedures, and troubleshooting. Covers backup manager, backup monitor, restore manager, and systemd automation.

## Overview

The Chaba backup system provides automated, comprehensive backup of infrastructure components to Google Drive with FUSE mount compatibility. It includes PostgreSQL database backups, Docker volume backups, configuration file backups, and documentation backups with automated retention policies and monitoring.

## Purpose

- **Data Protection**: Automated daily backups of all critical infrastructure components
- **Disaster Recovery**: Point-in-time restoration capabilities for databases, volumes, and configurations
- **Cloud Storage**: Google Drive integration with automatic sync and off-site storage
- **Monitoring**: Hourly backup monitoring with alerting for failures and issues
- **Retention**: Automatic rotation policies (30 days daily, 12 weeks weekly, 6 months monthly)

## Key Files

| File | Purpose |
|------|---------|
| `scripts/backup-manager.sh` | Main backup automation script |
| `scripts/backup-monitor.sh` | Backup monitoring and alerting script |
| `scripts/restore-manager.sh` | Backup restoration script |
| `scripts/test-backup.sh` | Backup system test suite |
| `systemd/chaba-backup.service` | Systemd service for backup execution |
| `systemd/chaba-backup.timer` | Systemd timer for daily backup scheduling |
| `systemd/chaba-backup-monitor.service` | Systemd service for monitoring |
| `systemd/chaba-backup-monitor.timer` | Systemd timer for hourly monitoring |

## Backup Architecture

### Storage Location
- **Primary**: `/home/tony/GoogleDrive/Tony AI/backup/chaba/`
- **Daily Backups**: `daily/` (30-day retention)
- **Weekly Backups**: `weekly/week_YYYY-WW/` (12-week retention)
- **Monthly Backups**: `monthly/month_YYYYMM/` (6-month retention)
- **Logs**: `logs/` (backup reports and monitoring reports)

### Backup Types
1. **Database**: PostgreSQL database with compression (`postgres_*.sql.gz`)
2. **Docker Volumes**: postgres_data, redis_data, weaviate_data (`volumes_*.tar.gz`)
3. **Configurations**: Docker Compose, environment files, SSOT, systemd (`configs_*.tar.gz`)
4. **Documentation**: Documentation directory (`docs_*.tar.gz`)

### FUSE Mount Compatibility
- **Issue**: Docker cannot directly write to FUSE-mounted Google Drive
- **Solution**: Use local temporary directories (`/tmp`) then copy to Google Drive
- **Benefit**: Maintains Docker functionality while using cloud storage

## Operational Procedures

### Daily Backup Execution

**Schedule**: Daily at 2:00 AM (systemd timer)

**Manual Execution**:
```bash
# Run full backup
./scripts/backup-manager.sh full

# Run specific backup type
./scripts/backup-manager.sh database
./scripts/backup-manager.sh volumes
./scripts/backup-manager.sh configs
./scripts/backup-manager.sh docs
```

**Expected Output**:
- Backup completion status
- Backup sizes and durations
- Verification results
- Error messages if any failures

### Backup Monitoring

**Schedule**: Hourly (systemd timer)

**Manual Monitoring**:
```bash
# Run all monitoring checks
./scripts/backup-monitor.sh all

# Run specific check
./scripts/backup-monitor.sh freshness
./scripts/backup-monitor.sh size
./scripts/backup-monitor.sh integrity
./scripts/backup-monitor.sh completeness
./scripts/backup-monitor.sh rotation
./scripts/backup-monitor.sh failures
./scripts/backup-monitor.sh disk
```

**Monitoring Checks**:
- **Freshness**: Latest backup age (36-hour threshold)
- **Size**: Backup size validation (1MB minimum threshold)
- **Integrity**: Gzip compression verification
- **Completeness**: All backup types present
- **Rotation**: Old backup cleanup verification
- **Failures**: Recent backup failure detection
- **Disk**: Available disk space monitoring

### Backup Restoration

**List Available Backups**:
```bash
./scripts/restore-manager.sh list
```

**Restore Database**:
```bash
./scripts/restore-manager.sh database /path/to/postgres_YYYYMMDD_HHMMSS.sql.gz
```

**Restore Volumes**:
```bash
./scripts/restore-manager.sh volumes /path/to/volumes_YYYYMMDD_HHMMSS
```

**Restore Configurations**:
```bash
./scripts/restore-manager.sh configs /path/to/configs_YYYYMMDD_HHMMSS
```

**Full Restoration**:
```bash
./scripts/restore-manager.sh full /path/to/backup_directory
```

**Safety Features**:
- User confirmation prompts for all restoration operations
- Pre-restoration verification
- Post-restoration validation
- Selective restoration by component

### Systemd Service Management

**Enable Backup Automation**:
```bash
# Enable and start backup timer
systemctl --user enable chaba-backup.timer
systemctl --user start chaba-backup.timer

# Enable and start monitoring timer
systemctl --user enable chaba-backup-monitor.timer
systemctl --user start chaba-backup-monitor.timer
```

**Check Service Status**:
```bash
# Check backup timer status
systemctl --user status chaba-backup.timer

# Check monitoring timer status
systemctl --user status chaba-backup-monitor.timer

# View next scheduled backup
systemctl --user list-timers chaba-backup.timer
```

**Manual Backup Trigger**:
```bash
# Trigger backup immediately
systemctl --user start chaba-backup.service
```

### Testing and Validation

**Run Backup System Tests**:
```bash
./scripts/test-backup.sh
```

**Test Coverage**:
- Script permissions verification
- Systemd service file validation
- Backup manager functionality
- Restore manager functionality
- Backup monitor functionality

## Troubleshooting

### Issue: Google Drive Not Mounted

**Symptoms**:
- Backup failures with mount errors
- Health monitor alerts for Google Drive not mounted
- Backup directory inaccessible

**Causes**:
- rclone mount not running
- Network connectivity issues
- Google Drive authentication expired

**Solutions**:
```bash
# Check mount status
mount | grep gdrive

# Remount Google Drive
rclone mount gdrive: /home/tony/GoogleDrive --daemon

# Check rclone configuration
rclone config show gdrive

# Check mount logs
journalctl -u rclone -f
```

### Issue: Backup Failed with FUSE Mount Error

**Symptoms**:
- Docker volume backup failures
- "Operation not permitted" errors
- Backup incomplete

**Causes**:
- Docker trying to write directly to FUSE mount
- FUSE mount compatibility issues

**Solutions**:
- The backup system now uses local temporary directories (`/tmp`) then copies to Google Drive
- Verify the fix is applied in `backup-manager.sh`
- Check for sufficient temporary disk space

### Issue: Backup Size Suspiciously Small

**Symptoms**:
- Backup monitor alerts for small backup size
- Database backup < 1MB

**Causes**:
- Database empty or corrupted
- Backup process interrupted
- Compression issues

**Solutions**:
```bash
# Check database size
docker exec postgres psql -U chaba -d chaba -c "SELECT pg_size_pretty(pg_database_size('chaba'));"

# Verify backup integrity
gzip -t /path/to/backup.sql.gz

# Manual backup test
docker exec postgres pg_dump -U chaba chaba | gzip > test-backup.sql.gz
```

### Issue: Backup Rotation Not Working

**Symptoms**:
- Old backups not being deleted
- Disk space filling up
- Backup count exceeding retention policy

**Causes**:
- Rotation logic not executing
- File permission issues
- Backup directory structure changes

**Solutions**:
```bash
# Manual cleanup of old backups
find /home/tony/GoogleDrive/Tony\ AI/backup/chaba/daily -name "*.sql.gz" -mtime +30 -delete
find /home/tony/GoogleDrive/Tony\ AI/backup/chaba/daily -name "*.tar.gz" -mtime +30 -delete

# Check backup directory structure
ls -la /home/tony/GoogleDrive/Tony\ AI/backup/chaba/daily/

# Verify rotation logic in backup-manager.sh
```

### Issue: Restoration Failed

**Symptoms**:
- Restore command errors
- Database restoration incomplete
- Volume restoration fails

**Causes**:
- Backup file corrupted
- Incorrect backup file path
- Database connection issues
- Docker volume conflicts

**Solutions**:
```bash
# Verify backup integrity
gzip -t backup-file.sql.gz
tar -tzf backup-file.tar.gz

# Check PostgreSQL container status
docker ps | grep postgres

# Test database connection
docker exec postgres psql -U chaba -d chaba -c "SELECT 1;"

# Remove conflicting volumes before restoration
docker volume rm volume_name
```

## Performance Metrics

**Backup Performance**:
- Full backup duration: 5-15 minutes
- Database backup: 2-5 minutes
- Volume backup: 3-8 minutes
- Configuration backup: 1-2 minutes
- Documentation backup: 1-2 minutes

**Storage Usage**:
- Daily backup growth: ~100-500MB per day
- Weekly backup retention: ~3-5GB
- Monthly backup retention: ~5-10GB
- Google Drive sync: Automatic

**Monitoring Performance**:
- Monitoring check duration: 10-30 seconds
- Alert generation: Immediate
- Report generation: 5-10 seconds

## Related Documentation

- **Google Drive Backup System**: `docs/kb/google-drive-backup-system.md` - Implementation details
- **SSOT Automation**: `docs/ssot/infrastructure/ssot.automation.yml` - Backup automation configuration
- **SSOT Health**: `docs/ssot/infrastructure/ssot.health.yml` - Backup monitoring configuration
- **System Automation**: `docs/kb/system-automation.md` - Systemd timer management

## Change History

| Date | Change | Author |
|------|--------|--------|
| 2026-08-13 | Initial creation with Google Drive integration and FUSE compatibility fixes | Devin |
| 2026-08-13 | Added troubleshooting section and performance metrics | Devin |