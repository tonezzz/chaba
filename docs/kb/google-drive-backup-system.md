---
category: operations
---

# Google Drive Backup System with FUSE Compatibility

## Context
The Chaba infrastructure backup system was migrated from local storage to Google Drive for cloud-based backup storage. This required FUSE mount compatibility fixes due to Docker's inability to directly mount FUSE filesystems.

## Related Documentation
- `scripts/backup-manager.sh` - Main backup script
- `scripts/backup-monitor.sh` - Backup monitoring script
- `scripts/restore-manager.sh` - Backup restoration script
- `scripts/health-monitor.sh` - Health monitoring with Google Drive checks
- `systemd/chaba-backup.service` - Backup systemd service
- `systemd/chaba-backup.timer` - Backup systemd timer
- `docs/ssot/infrastructure/ssot.automation.yml` - Automation configuration
- `docs/ssot/infrastructure/ssot.health.yml` - Health service configuration

## Tags
- backup, google-drive, fuse, docker, systemd, automation, infrastructure

## See also

- [Google Drive Backup Architecture](google-drive-backup-architecture.md)
- [Google Drive Backup Automation](google-drive-backup-automation.md)
- [Google Drive Backup Troubleshooting](google-drive-backup-troubleshooting.md)
