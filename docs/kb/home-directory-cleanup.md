---
category: operations
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

## Related Documentation

- **Disk Space Management**: `disk-space-management.md` - Docker and HuggingFace cache cleanup
- **Partition Management**: System documentation for partition layout and mounting
- **System Administration**: General system maintenance procedures

## Change History

| Date | Change | Author |
|------|--------|--------|
| 2026-08-12 | Initial creation | Devin (session fortune-almond) |

## See also

- [Home Directory Cleanup Implementation](home-directory-cleanup-implementation.md)
- [Home Directory Cleanup Operations](home-directory-cleanup-operations.md)
