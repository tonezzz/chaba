---
category: operations
---

# System Architecture

### Storage Location
- **Previous:** `/home/tony/backups/chaba` (local storage)
- **Current:** `/home/tony/GoogleDrive/Tony AI/backup/chaba` (Google Drive FUSE mount)
- **Mount Point:** `/home/tony/GoogleDrive` (rclone FUSE mount)

### Backup Types
- **Database:** PostgreSQL dumps (postgres_*.sql.gz)
- **Docker Volumes:** postgres_data, redis_data, weaviate_data
- **Configurations:** Docker Compose files, environment files, SSOT, systemd
- **Documentation:** docs directory

### Retention Policy
- **Daily:** 30 days
- **Weekly:** 12 weeks
- **Monthly:** 6 months

## FUSE Mount Compatibility Issues

### Problem
Docker cannot directly mount FUSE filesystems, causing backup failures:
```
docker: Error response from daemon: error while creating mount source path 
'/home/tony/GoogleDrive/Tony AI/backup/chaba/daily/volumes_*': 
mkdir /home/tony/GoogleDrive: file exists
```

### Solution
Use local temporary directories for Docker operations, then copy to Google Drive:

**Docker Volume Backups:**
```bash
# Use local temporary directory
local_backup_dir="/tmp/chaba_volumes_${BACKUP_DATE}"
final_backup_dir="$BACKUP_ROOT/daily/volumes_${BACKUP_DATE}"

# Docker backup to local directory
docker run --rm -v "$volume:/volume_data" -v "$local_backup_dir:/backup" \
    alpine tar czf "/backup/${volume}.tar.gz" -C /volume_data .

# Copy to Google Drive
cp "$local_backup_dir/${volume}.tar.gz" "$final_backup_dir/"

# Cleanup
rm -rf "$local_backup_dir"
```

**Configuration Backups:**
```bash
# Same pattern for configs and docs
local_backup_dir="/tmp/chaba_configs_${BACKUP_DATE}"
final_backup_dir="$BACKUP_ROOT/daily/configs_${BACKUP_DATE}"

# Create backups locally
tar czf "$local_backup_dir/web.tar.gz" -C "$(dirname "$dir")" "$dir_name"

# Copy to Google Drive
cp -r "$local_backup_dir"/* "$final_backup_dir/"

# Cleanup
rm -rf "$local_backup_dir"
```

