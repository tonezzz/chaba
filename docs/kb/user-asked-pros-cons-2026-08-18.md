# User Asked Pros Cons

## What it is

User Asked Pros Cons

## Context/Background

**Date:** 2026-08-18
**Session Context:** 

## Key Details

### Technical Details
- The user asked for pros & cons and a final recommendation for implementing MDDB `get_page`, `list_sections`, and `read_tree`.
- Compared five methods: (A) upstream MDDB core, (B) local MCP bridge/wrapper, (C) extend Claude `mddb-bridge.py`, (D) keep `docs`/`docs-trade` alongside `mddb`, (E) hybrid bridge-now/upstream-later.
- Final recommendation: build a local `mcp-mddb-bridge` (FastMCP in `chaba-omen/mcp/mcp-mddb/`) immediately, using existing `mddb.search_documents` for exact `original_path` retrieval and client-side prefix filtering, while opening a parallel upstream `feature/mddb-page-tools` branch for the long-term clean implementation.
- This is pragmatic because the `tradik/mddb` source is not in the workspace, the bridge can be deployed now, and it can be deprecated once upstream MDDB absorbs the tools.

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
