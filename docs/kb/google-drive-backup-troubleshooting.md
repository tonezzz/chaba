---
category: operations
---

# Troubleshooting

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

