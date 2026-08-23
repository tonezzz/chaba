# Mcp_Focus Sweep Bulk-Defer Current

## What it is

Mcp_Focus Sweep Bulk-Defer Current

## Context/Background

**Date:** 2026-08-18
**Session Context:** 

## Key Details

### Technical Details
mcp_focus sweep bulk-defer and current parked foci:
- _sweep_candidates now scans ssot.focus.current.yml active/parked sections, so parked foci like Yomi are included.
- Added bulk_session parameter to mcp_focus; when provided in sweep mode it bulk-defers all non-hold candidates to that session.
- _bulk_defer updates focus-inbox drafts to status: deferred, parks backlog items in ssot.focus.yml, and parks current-section foci in ssot.focus.current.yml with deferred metadata.
- Updated mcp_debug and mcp_focus server schemas and ssot.mcp-focus.yml docs.
- Fixed active focus source path for Switch MDDB to point to the processed inbox file.
- Archived Gemini key rotation in ssot.focus.yml backlog as completed to remove active-focus duplication.

Re-assessment:
- The sweep now correctly holds the active focus (Switch MDDB embedding provider) and lists 6 remaining candidates.
- Single bulk_session is enough for a common pool; per-branch/per-session defer still requires separate mcp_focus defer calls or a future --session-plan.

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
