# Auto KB Creation Skill

Automatically creates KB entries based on KB review sections from assistant responses.

## What it does

This skill analyzes KB review sections from assistant responses and automatically creates knowledge base entries for high-value information, reducing manual overhead while maintaining KB quality.

**Automatic Invocation**: This skill is automatically invoked at the end of every session that contains KB-worthy information in the KB review section, as per the mandatory KB processing rules in `.windsurfrules`.

## When to use

Invoke this skill when:
- A KB review section contains KB-worthy information (automatic at end of sessions)
- You want to automate KB entry creation during work (with user confirmation)
- You need to check for redundancy with existing entries
- You want to follow consistent KB entry structure

## What it needs

Input (one of):
- CLI argument: `node auto-kb.mjs "<kb-review-content>" ["<context>"]`
- Environment: `KB_REVIEW_CONTENT="..."` and optional `KB_SESSION_CONTEXT="..."`, plus either `MCP_REDUNDANCY_FILE` or `MCP_REDUNDANCY_RESULT`
- Stdin: `echo "..." | node auto-kb.mjs`

The KB review section should be a concise summary of decisions, discoveries, or fixes from the session.

`auto-kb` does **not** call MCP tools itself. The assistant must provide MDDB redundancy results before invoking it:

1. Call `mcp_call_tool mddb semantic_search` for the relevant collections.
2. Combine the results into an array and either:
   - Set `MCP_REDUNDANCY_RESULT` to the JSON string, or
   - Write the JSON to a file and set `MCP_REDUNDANCY_FILE` to its path.
3. After `auto-kb` creates the file, call `mcp_call_tool mddb add_document` to index it.

## Processing steps

1. **Analyzes KB review content** for KB-worthiness triggers:
   - Significant bug fixes (data corruption, security vulnerabilities)
   - New patterns/workarounds
   - New systems/integrations
   - Configuration optimizations
   - Language-specific issues
   - Root cause analyses
   - Reusable patterns

2. **Checks for redundancy** with existing KB entries using the MDDB result supplied by the assistant:
   - Uses `MCP_REDUNDANCY_RESULT` or `MCP_REDUNDANCY_FILE` if provided
   - Falls back to local file-based check if an MDDB result is not provided
   - Skips creation if high redundancy is detected

3. **Creates KB entries** following the standard template:
   - Title and description
   - Context/background
   - Key technical details
   - Usage/commands
   - Troubleshooting
   - Related documentation
   - Tags

4. **Places entries** in the correct location:
   - `/home/tony/CascadeProjects/chaba-tony-dell/docs/kb/` (local file) or `KB_DIR` if overridden

5. **Indexes in MDDB** for future semantic search:
   - The assistant calls `mcp_call_tool mddb add_document` with the collection, filename, and metadata
   - `auto-kb` outputs the chosen collection and filename so the assistant can index it

## Quality criteria

Only creates entries for:
- **Operational value**: Helps with current/future operations
- **Reusability**: Can be applied to similar situations  
- **Prevention**: Helps prevent recurring issues
- **Specificity**: Contains actionable technical details
- **Context**: Includes when/why it's relevant

Does NOT create entries for:
- Temporary commands or one-off output
- Obvious trivia or well-known information
- Transient debugging steps without lasting value
- Personal preferences without technical justification

## Example usage

```bash
# Basic (no MDDB redundancy result, uses file-based fallback)
node .agents/skills/auto-kb/auto-kb.mjs "Created daily2 page with calendar layout..."

# With pre-computed MDDB redundancy result as a JSON file
KB_REVIEW_CONTENT="Created daily2 page..." \
MCP_REDUNDANCY_FILE=/tmp/kb-redundancy.json \
  node .agents/skills/auto-kb/auto-kb.mjs

# Or pass the result directly as a JSON string
KB_REVIEW_CONTENT="Created daily2 page..." \
MCP_REDUNDANCY_RESULT='[{"collection":"chaba-features","key":"...","score":0.85,"title":"..."}]' \
  node .agents/skills/auto-kb/auto-kb.mjs

# Or piped
echo "Created daily2 page..." | MCP_REDUNDANCY_FILE=/tmp/kb-redundancy.json node .agents/skills/auto-kb/auto-kb.mjs
```

## Related documentation

- `.windsurf/workflows/auto-kb-creation.md` - Detailed workflow documentation
- `docs/kb/` - Existing KB entries for reference patterns
