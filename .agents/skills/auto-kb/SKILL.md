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
- Environment: `KB_REVIEW_CONTENT="..."` and optional `KB_SESSION_CONTEXT="..."`
- Stdin: `echo "..." | node auto-kb.mjs`

The KB review section should be a concise summary of decisions, discoveries, or fixes from the session.

## Processing steps

1. **Analyzes KB review content** for KB-worthiness triggers:
   - Significant bug fixes (data corruption, security vulnerabilities)
   - New patterns/workarounds
   - New systems/integrations
   - Configuration optimizations
   - Language-specific issues
   - Root cause analyses
   - Reusable patterns

2. **Checks for redundancy** with existing KB entries using MDDB:
   - Uses MDDB semantic search across KB collections (kb-development, kb-features, kb-operations, kb-system)
   - Provides relevance scores (0.4-1.0) for similarity detection
   - Falls back to local file-based check if MDDB unavailable
   - Updates existing entries instead of creating duplicates
   - Archives outdated entries if needed

3. **Creates KB entries** following the standard template:
   - Title and description
   - Context/background
   - Key technical details
   - Usage/commands
   - Troubleshooting
   - Related documentation
   - Tags

4. **Places entries** in the correct location:
   - `/home/tony/CascadeProjects/chaba/docs/kb/` (local file)
   - Automatically indexes in MDDB for semantic search

5. **Indexes in MDDB** for future semantic search:
   - Automatically determines appropriate collection based on content
   - Adds metadata (title, source, creation date, auto-generated flag)
   - Enables future redundancy checking via semantic search

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
node .agents/skills/auto-kb/auto-kb.mjs "Created daily2 page with calendar layout for Yomi daily summaries. Required web stack restart to pick up new file. Page now accessible at /apps/yomi/daily2/index.html with basic auth. Uses existing API endpoints and follows project styling conventions."

# Or via environment
KB_REVIEW_CONTENT="Created daily2 page..." node .agents/skills/auto-kb/auto-kb.mjs

# Or piped
echo "Created daily2 page..." | node .agents/skills/auto-kb/auto-kb.mjs
```

## Related documentation

- `.windsurf/workflows/auto-kb-creation.md` - Detailed workflow documentation
- `docs/kb/` - Existing KB entries for reference patterns
