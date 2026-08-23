# Assessed Configured Devin Servers

## What it is

Assessed Configured Devin Servers

## Context/Background

**Date:** 2026-08-18
**Session Context:** 

## Key Details

### Technical Details
- Assessed the 15 configured Devin MCP servers in `~/.config/devin/mcp_config.json`.
- Confirmed `playlive` and `playlive-macbook` expose identical tool schemas but target different hosts (`playlive` → `http://tony-dell:9230`, `playlive-macbook` → `http://100.124.59.112:9231`), so both are valid if both browser daemons are used.
- Recommend renaming the generic `playlive` MCP server to `playlive-dell` for clarity, or keeping it only if the tony-dell endpoint remains active.
- Confirmed `docs` (`/home/tony/CascadeProjects/chaba/docs`) and `docs-trade` (`/home/tony/CascadeProjects/trade/docs`) expose the same three tools (`search_docs`, `get_page`, `list_sections`) over different corpora.
- MDDB already indexes both chaba (`chaba-*`, `ssot-*`, `yomi-*`) and trade (`trade-*`) collections with 341 documents, so MDDB supersedes the docs servers for semantic and filtered search.
- `docs`/`docs-trade` still provide path-based `get_page` and `list_sections` tools that MDDB does not expose, so they remain as fallback/legacy until those capabilities migrate to MDDB or usage of direct page retrieval is removed.
- Other MCP servers (`github`, `postgres`, `mcp-weaviate`, `mcp-llama`, `mcp-gpu`, `mcp-health`, `mcp-debug`, `yomi`, `workflows`, `alphavantage`) are not duplicated and should stay.

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
