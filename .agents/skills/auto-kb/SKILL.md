# Auto KB Creation Skill

Automatically creates KB entries based on KB review sections from assistant responses.

## What it does

This skill analyzes KB review sections and automatically creates knowledge base entries for high-value information, reducing manual overhead while maintaining KB quality.

## When to use

Invoke this skill when:
- A KB review section contains KB-worthy information
- You want to automate KB entry creation
- You need to check for redundancy with existing entries
- You want to follow consistent KB entry structure

## What it needs

Input parameters:
- `kb_review_content`: The KB review section text from an assistant response
- `session_context`: Optional context about the session/work done

## What it does

1. **Analyzes KB review content** for KB-worthiness triggers:
   - Significant bug fixes (data corruption, security vulnerabilities)
   - New patterns/workarounds
   - New systems/integrations
   - Configuration optimizations
   - Language-specific issues
   - Root cause analyses
   - Reusable patterns

2. **Checks for redundancy** with existing KB entries:
   - Searches existing entries for overlapping content
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
   - `/home/tony/CascadeProjects/chaba-yomi/docs/kb/`

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

```
/auto-kb "Created daily2 page with calendar layout for Yomi daily summaries. Required web stack restart to pick up new file. Page now accessible at /apps/yomi/daily2/index.html with basic auth. Uses existing API endpoints and follows project styling conventions."
```

## Related documentation

- `.windsurf/workflows/auto-kb-creation.md` - Detailed workflow documentation
- `docs/kb/` - Existing KB entries for reference patterns
