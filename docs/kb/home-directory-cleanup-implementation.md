---
category: operations
---

# Implementation/Architecture

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

