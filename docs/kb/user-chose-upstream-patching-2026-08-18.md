# User Chose Upstream Patching

## What it is

User Chose Upstream Patching

## Context/Background

**Date:** 2026-08-18
**Session Context:** 

## Key Details

### Technical Details
- The user chose upstream patching (option 2) for adding `get_page`, `list_sections`, and `read_tree` to MDDB.
- Assessed current deployment: MDDB runs from prebuilt `tradik/mddb:latest` pulled by `chaba-kbman/stacks/web/mddb/docker-compose.yml`; there is a Claude `mddb-bridge.py` wrapper and `ssot.mcp.yml` filtered tools list.
- Suggested: fork/branch the MDDB source, create `feature/mddb-page-tools` (or `chaba-patches`), build a custom tagged image, pin it in docker-compose, and update the Claude bridge and `ssot.mcp.yml` `filtered_tools` to expose the new tools.
- Proposed activating this as the next branch focus since `ssot.focus.current.yml` currently has an empty Active Branch Focus.

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
