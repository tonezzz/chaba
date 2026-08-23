# Tony-Dell Sync Rsync And Mcp-Focus Hardening Completed

## What it is

Tony-Dell Sync Rsync And Mcp-Focus Hardening Completed

## Context/Background

**Date:** 2026-08-18
**Session Context:** 

## Key Details

### Technical Details
Tony-Dell sync, rsync, and mcp-focus hardening (completed):
- Disabled the stale tony-omen `focus-dispatcher-overnight.timer` using `mcp_system`.
- Confirmed `chaba-funnel-docs-sync` uses `rsync -avP --delete --checksum`.
- Added `node scripts/ssot-validate-all.mjs` to `scripts/overnight-focus-review.py`; it aborts on validation errors before focus-dispatcher.
- Re-enabled `mcp-health-to-inbox` by removing `SKIP_HEALTH` from `ssot.night-jobs.yml`.
- Made `yomi-backup` host-agnostic: updated `/home/tony/.local/bin/yomi-backup.sh` on tony-dell to use `BACKUP_HOST`/`BACKUP_USER` environment variables with `tony-omen` defaults and updated `ssot.night-jobs.yml`.
- Scaffolded `mcp_focus` package (`scripts/mcp_focus/__init__.py` and `server.py`) and created `~/.config/systemd/user/mcp-focus.service` on tony-dell.
- Archived the completed focus and left the active branch empty.

Conventions:
- `mcp_system` is the right tool for exact `systemctl` commands on a remote host.
- `yomi-backup.sh` now supports `BACKUP_HOST`/`BACKUP_USER` overrides for failover backups.
- The overnight focus-review pipeline now validates all SSOT files before committing/pushing.

### Implementation
- **Status:** Documented
- **Date:** 2026-08-18
- **Location:** docs/kb/

## Related Documentation

- **[KB Migration Summary](kb-migration-summary-2026-08-13.md)** - Related migration work

## Tags

- **infrastructure**: System infrastructure changes
- **documentation**: Knowledge base documentation
- **migration**: System migration and updates
