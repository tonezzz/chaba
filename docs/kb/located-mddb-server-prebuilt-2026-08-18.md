# Located Mddb Server Prebuilt

## What it is

Located Mddb Server Prebuilt

## Context/Background

**Date:** 2026-08-18
**Session Context:** 

## Key Details

### Technical Details
- Located the MDDB server: it is a prebuilt `tradik/mddb:latest` Docker image (see `chaba-kbman/stacks/web/mddb/docker-compose.yml`); source is not present in the local workspace.
- The existing MCP tool surface is built into the binary, so `get_page`, `list_sections`, and `read_tree` cannot be added to the `mddb` server directly from this workspace.
- Confirmed `mddb.search_documents` can retrieve a specific doc with `filter_meta: {original_path: "..."}` and can list all docs in a collection with `limit`/`fields`.
- Confirmed `filter_meta` prefix operators (`$like`, `$regex`) are not honored, so `list_sections`/`read_tree` would need client-side prefix filtering if implemented as a wrapper.
- No implementation was committed; user needs to choose between an upstream patch (requires `tradik/mddb` source) or a local `mcp-mddb-bridge` wrapper.

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
