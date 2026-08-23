# Proposed Adding Get_Page List_Sections

## What it is

Proposed Adding Get_Page List_Sections

## Context/Background

**Date:** 2026-08-18
**Session Context:** 

## Key Details

### Technical Details
- Proposed adding `get_page` and `list_sections` tools to the `mddb` MCP server so it can serve as a drop-in replacement for the legacy `docs` and `docs-trade` servers.
- Proposed a new "recursive section reading" tool (e.g., `read_tree` or `read_recursive`) that fetches a parent section and all descendant documents in one call, enabling multi-part reference docs to be retrieved at once.
- Noted that MDDB already indexes both chaba and trade corpora, so these tools would remove the last remaining reason to keep the separate `docs`/`docs-trade` fallbacks (`get_page` / `list_sections` direct path retrieval).
- No implementation or file changes were made yet; user asked for wording/scope elaboration first.

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
