---
category: operations
---

# Operational Procedures

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

