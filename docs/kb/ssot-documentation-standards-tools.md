---
category: operations
---

# Tools and Automation

### Validation Scripts
- **SSOT Validation**: `bash scripts/validate-configs.sh`
- **Focus Validation**: `node scripts/validate-focus.mjs`
- **MCP Config Generation**: `python3 scripts/generate-mcp-configs.py`
- **MCP Source Validation**: `python3 scripts/ssot-validate-mcp-sources.py` — validates that every `operational` MCP server's implementation file exists on disk. It reads the repo-local `docs/ssot/infrastructure/ssot.mcp.yml` and resolves `per_host` overrides for the current host, so it no longer fails on stale cross-repo paths. (2026-09-02)

### Documentation Search Standards
**IMPORTANT: Assistant workflow for documentation searches**

1. **Primary Method**: Use MCP docs server for all documentation searches
   - `mcp_call_tool docs search_docs "query" limit` for broad searches
   - `mcp_call_tool docs get_page "path"` for specific page retrieval
   - `mcp_call_tool docs list_sections` for browsing structure

2. **Secondary Method**: Use ssot-search skill for SSOT YAML pattern matching
   - Exact YAML structure queries
   - SSOT-specific searches
   - When you know exact terms to search for

3. **Fallback Guidelines**: Only use traditional tools (grep, read, find) after:
   - Attempting MCP docs server and identifying specific issue
   - Suggesting the fix to the user (e.g., reinstall MCP server, check config)
   - Getting user confirmation to proceed with fallback
   - **Never silently fall back** without explaining the issue and proposed fix

4. **MCP Troubleshooting**: When MCP docs server fails:
   - Check MCP config: `/home/tony/.config/devin/mcp_config.json`
   - Test connectivity: `mcp_list_tools mddb`
   - Suggest specific fix based on error
   - Reinstall if needed: restart MDDB container

**Reference**: See `docs/kb/documentation-search.md` for comprehensive search methods guide

### Automation Integration
- Consider git hooks for pre-commit validation
- CI/CD integration for automated validation
- Scheduled validation for consistency checks

## Troubleshooting

### Common Validation Errors
- **Missing title field**: Add `title:` to the SSOT file
- **Invalid YAML**: Check indentation, quotes, colons
- **Duplicate entries**: Rename or remove duplicates
- **Hostname violations**: Replace IPs with `.local` hostnames

### SSOT Drift Recurrence
- If drift recurs, identify source of changes in downstream locations
- Establish change control process for downstream locations
- Consider automated synchronization for frequently changed files
- Review access permissions to prevent unauthorized modifications

### Cross-Reference Issues
- **Invalid reference**: Check if referenced file/section exists
- **Broken links**: Update references when files move
- **Circular dependencies**: Restructure to remove cycles

