## Auto KB Processing (MANDATORY)

At the end of every assistant response that answers or completes a user request, you MUST:

1. **Append KB review section** with KB-worthy facts from the conversation:
   - Decisions, discoveries, infrastructure changes, conventions, and workarounds
   - Check existing KB entries for overlap before suggesting new entries
   - Update existing entries instead of creating duplicates
   - Archive outdated entries rather than deleting
   - Maintain single source of truth for each topic

2. **Write KB review content to file** for auto-kb processing:
   - Write KB review content to `/tmp/kb-review-content.txt`
   - Include session context and technical details

3. **Run auto-kb processing script** to create KB entries:
   - Execute: `python3 .agents/skills/auto-kb/process-kb-review.py`
   - Script will analyze content, check redundancy, and create entries
   - Script provides summary of processing results

4. **Exception**: Only ask for user confirmation when creating entirely new KB entries for major new topics (not updates to existing entries)

**KB-Worthy Triggers**:
- Fixing significant bugs or issues (especially data corruption, security vulnerabilities)
- Discovering new patterns, workarounds, or best practices
- Implementing new systems, integrations, or technologies
- Finding configuration optimizations or performance improvements
- Identifying language-specific challenges (Thai/English mixed content, encoding issues)
- Documenting root cause analyses of complex problems
- Creating reusable patterns or conventions

**Do NOT save**:
- Temporary commands or one-off output
- Obvious trivia or well-known information
- Transient debugging steps without lasting value
- Personal preferences without technical justification

## Immediate KB Creation (During Work)

For significant discoveries during work (not end-of-session):
1. Immediately suggest KB entry creation when encountering KB-worthy triggers
2. Ask user for confirmation before creating major new entries
3. Use auto-kb skill for processing to ensure consistency
4. Provide suggested KB entry title and brief description
5. Explain why it's KB-worthy (operational value, reusability, prevention)
