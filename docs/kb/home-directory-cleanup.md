---
title: Old Home Directory Cleanup After Partition Migration
description: Systematic methodology for identifying and removing duplicate data from old home directories after partition migration, with specific case study recovering 54GB from root partition
tags: [partition, disk-space, cleanup, migration, home-directory, system-administration]
created: 2026-08-12
updated: 2026-08-12
category: operations
related: [disk-space-management.md]
search_keywords: [home directory cleanup, partition migration, disk space recovery, old home removal, duplicate data cleanup]
---

# Old Home Directory Cleanup After Partition Migration

**Abstract**: Systematic approach to cleaning up old home directories after partition migration, using comparison techniques to identify safe-to-delete items while preserving critical data. Case study: recovered 54GB from root partition, reducing usage from 91% to 35%.

## Overview

After migrating user data to a dedicated home partition, the old home directory on the root partition often contains duplicate or superseded data that can be safely removed. This methodology provides a systematic approach to identify and remove redundant data while preserving critical configurations and unique files.

## Purpose

- Recover disk space from root partition after home partition migration
- Remove duplicate/superseded data without losing critical configurations
- Maintain system stability by preserving authentication keys and unique settings
- Provide reusable methodology for future partition cleanup operations

## Key Files

| Location | Purpose |
|----------|---------|
| `/home/tony` | Active home directory (dedicated partition) |
| `/mnt/root-partition/home/tony` | Old home directory (root partition) |
| `/mnt/home-partition` | Mounted home partition |

## Implementation/Architecture

### Cleanup Methodology

**Phase 1: Assessment**
1. Compare partition usage: `df -h`
2. Compare directory structures between old and new home
3. Identify size of major directories: `du -sh`
4. Check for unique vs duplicate content

**Phase 2: High-Confidence Cleanup**
Items safe to remove immediately:
- Duplicate project directories (CascadeProjects)
- Identical downloads folders
- Cache directories (.cache)
- Container storage (.local/share/containers)
- Application configs with newer versions in active home
- Duplicate virtual environments
- Temporary files (logs, bash history)

**Phase 3: Critical Data Preservation**
Items to keep or verify:
- SSH keys (.ssh)
- GPG keys (.gnupg)
- Shell configurations (.bashrc, .profile, .gitconfig)
- Unique application configurations
- User-specific data not present in active home

**Phase 4: Verification**
- Confirm no services depend on old home paths
- Check for symlinks pointing to old home
- Verify system functionality after cleanup

### Comparison Techniques

**Directory comparison:**
```bash
# Compare directory contents
diff -q /old/home/path /new/home/path

# Compare specific files
diff /old/home/.bashrc /new/home/.bashrc

# Find unique items
diff -r /old/home /new/home | grep "Only in"
```

**Size analysis:**
```bash
# Directory sizes
du -sh /old/home/* | sort -hr

# Specific subdirectory analysis
du -sh /old/home/.config/*
```

## Operational Procedures

### Case Study: Root Partition Cleanup (2026-08-12)

**Initial State:**
- Root partition: 91% full (88GB used of 98GB)
- Old home location: `/mnt/root-partition/home/tony`
- Active home: `/home/tony` (dedicated partition)

**High-Confidence Removals (~45GB):**
```bash
# Remove duplicate projects
sudo rm -rf /mnt/root-partition/home/tony/CascadeProjects

# Remove duplicate downloads
sudo rm -rf /mnt/root-partition/home/tony/Downloads

# Remove duplicate screenshots
sudo rm -f /mnt/root-partition/home/tony/*.png

# Remove cache
sudo rm -rf /mnt/root-partition/home/tony/.cache

# Remove old containers (active home has newer version)
sudo rm -rf /mnt/root-partition/home/tony/.local/share/containers

# Remove old application configs
sudo rm -rf /mnt/root-partition/home/tony/.config/Devin
sudo rm -rf /mnt/root-partition/home/tony/.config/google-chrome
sudo rm -rf /mnt/root-partition/home/tony/.config/Claude

# Remove duplicate virtual environments
sudo rm -rf /mnt/root-partition/home/tony/venv-embeddings
sudo rm -rf /mnt/root-partition/home/tony/yomi-linux-x64

# Remove temporary files
sudo rm -f /mnt/root-partition/home/tony/.xsession-errors*
sudo rm -f /mnt/root-partition/home/tony/.xorgxrdp*.log*
sudo rm -f /mnt/root-partition/home/tony/.bash_history
```

**Additional Cleanup (~9GB):**
```bash
# Remove remaining .local (active home has more current version)
sudo rm -rf /mnt/root-partition/home/tony/.local

# Remove remaining config files
sudo rm -rf /mnt/root-partition/home/tony/.config

# Remove snap and standard directories
sudo rm -rf /mnt/root-partition/home/tony/snap
sudo rm -rf /mnt/root-partition/home/tony/Desktop
sudo rm -rf /mnt/root-partition/home/tony/Documents
# ... (other standard directories)
```

**Items Preserved:**
- Pictures directory (moved to active home)
- Critical authentication keys (verified identical in active home)

**Final Results:**
- Root partition usage: 91% → 35% (88GB → 34GB used)
- Space freed: ~54GB
- Available space: 64GB
- Old home directory: Completely removed

### Safety Guidelines

**Before deletion:**
1. Always compare contents before removing
2. Verify active home has newer/larger versions of application data
3. Check for symlinks or dependencies on old home paths
4. Preserve authentication keys even if they appear identical

**During deletion:**
1. Start with high-confidence items (cache, temp files)
2. Remove medium-confidence items after verification
3. Keep critical items until final verification
4. Monitor system stability after each major deletion

**After deletion:**
1. Verify system functionality
2. Check application configurations
3. Confirm no broken symlinks
4. Monitor partition usage over time

## Troubleshooting

### Issue: Accidental deletion of critical data
- **Symptoms**: Applications failing, authentication issues, missing configurations
- **Causes**: Insufficient comparison before deletion, not checking for unique content
- **Solutions**: Restore from backups if available; reconfigure applications manually

### Issue: System instability after cleanup
- **Symptoms**: Services failing to start, missing configuration files
- **Causes**: Removed active configuration files, broken symlinks
- **Solutions**: Check system logs, restore critical configs from backup, verify service dependencies

### Issue: Insufficient space recovery
- **Symptoms**: Partition still high usage after cleanup
- **Causes**: Large hidden files, other directories consuming space
- **Solutions**: Use `du -sh` to identify large directories, check for large log files, analyze entire partition usage

## Performance Metrics

**Case Study Results (2026-08-12):**
- **Space recovered**: 54GB from root partition
- **Usage reduction**: 91% → 35% (56 percentage points)
- **Time required**: ~30 minutes for assessment and cleanup
- **Risk level**: Very low (systematic comparison approach)
- **System impact**: None (all critical data preserved)

## Related Documentation

- **Disk Space Management**: `disk-space-management.md` - Docker and HuggingFace cache cleanup
- **Partition Management**: System documentation for partition layout and mounting
- **System Administration**: General system maintenance procedures

## Change History

| Date | Change | Author |
|------|--------|--------|
| 2026-08-12 | Initial creation | Devin (session fortune-almond) |
