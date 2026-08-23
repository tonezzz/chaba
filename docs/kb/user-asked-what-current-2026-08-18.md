# User Asked What Current

## What it is

User Asked What Current

## Context/Background

**Date:** 2026-08-18
**Session Context:** 

## Key Details

### Technical Details
- The user asked what the current workflow does when 2 or more foci overlap.
- The canonical policy is in docs/ssot/ssot.focus.current.yml and docs/ssot/infrastructure/ssot.mcp-focus.yml: at most one active shared focus and one active branch focus at any time.
- If a request matches both active foci, prefer the branch if the request mentions it, the shared focus if it matches, otherwise ask the user which to continue.
- If new strategic work must start while a shared focus is active, the interrupt case says to park the shared focus, activate the new work as a branch focus, and return later.
- For overlapping/redundant SSOT topics, docs/ssot/ssot.file-optimization.yml has planned Phase 3 (Redundancy merge/split) and Conflict detection, but it is not started.

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
