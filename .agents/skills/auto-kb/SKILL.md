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

Input parameters:
- `kb_review_content`: The KB review section text from an assistant response (automatically read from `/tmp/kb-review-content.txt`)
- `session_context`: Optional context about the session/work done

## Processing steps

1. **Run the processing script**: Execute `process-kb-review.py` to analyze KB review content
2. **Analyzes KB review content** for KB-worthiness triggers:
   - Significant bug fixes (data corruption, security vulnerabilities)
   - New patterns/workarounds
   - New systems/integrations
   - Configuration optimizations
   - Language-specific issues
   - Root cause analyses
   - Reusable patterns

3. **Checks for redundancy** with existing KB entries:
   - Searches existing entries for overlapping content
   - Updates existing entries instead of creating duplicates
   - Archives outdated entries if needed
   - Excludes general guide files from redundancy checks

4. **Creates KB entries** following the standard template:
   - Title and description
   - Context/background
   - Key technical details
   - Usage/commands
   - Troubleshooting
   - Related documentation
   - Tags

5. **Places entries** in the correct location:
   - `/home/tony/CascadeProjects/chaba-kbman/docs/kb/`

## Implementation

**Processing Script**: `.agents/skills/auto-kb/process-kb-review.py`

**Input Method**: Reads KB review content from `/tmp/kb-review-content.txt` (created by assistant)

**Redundancy Detection**: Uses specific term matching and excludes general guide files

**Entry Creation**: Follows standard KB template with proper formatting

## Usage

When this skill is invoked, it automatically:
1. Reads KB review content from `/tmp/kb-review-content.txt`
2. Processes the content to extract KB-worthy facts
3. Checks for redundancy with existing entries
4. Creates new KB entries for non-redundant content
5. Provides summary of processing results

**Example invocation:**
```bash
# Assistant creates KB review content file
echo "KB-worthy facts..." > /tmp/kb-review-content.txt

# Skill is invoked automatically or manually
cd /home/tony/CascadeProjects/chaba-kbman
python3 .agents/skills/auto-kb/process-kb-review.py
```

**Assistant Integration:**
When appending KB review section to response, assistant should:
1. Write KB review content to `/tmp/kb-review-content.txt`
2. Invoke this skill to process the content
3. Skill will automatically create appropriate KB entries

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
