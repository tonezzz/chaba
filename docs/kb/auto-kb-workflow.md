# Auto-KB Workflow Automation

## What it is

Fully automatic knowledge base entry creation workflow that processes KB review sections at the end of assistant sessions without requiring manual user confirmation.

## Context/Background

Updated 2026-08-04 to transition from manual to automatic KB processing workflow. The previous workflow required user confirmation before invoking the auto-kb skill, which created friction and reduced KB update consistency. The new workflow is fully automatic while maintaining quality through built-in redundancy checking.

## Key Details

### Technical Details
- **Skill Location**: `.agents/skills/auto-kb/SKILL.md`
- **Implementation**: `.agents/skills/auto-kb/auto-kb.mjs`
- **KB Directory**: `/home/tony/CascadeProjects/chaba/docs/kb/`
- **Workflow Documentation**: `.windsurf/workflows/auto-kb-creation.md`
- **Rules Configuration**: `.windsurfrules`

### Implementation

**New Automatic Workflow:**
1. Assistant appends KB review section to response (MANDATORY)
2. Assistant automatically invokes auto-kb skill (MANDATORY)
3. Auto-kb processes redundancy and updates/creates entries
4. User can review if desired (optional)

**Exception Process:**
- Major new topics during work still require user confirmation before creation
- This exception applies to entirely new topics, not updates to existing entries

**Auto-KB Skill Capabilities:**
- Analyzes KB review content for KB-worthiness triggers
- Checks redundancy with existing KB entries
- Updates existing entries instead of creating duplicates
- Archives outdated entries when needed
- Follows consistent KB entry structure and quality criteria

### Files/Components
- `.windsurfrules` - Mandatory KB processing rules (updated to require automatic invocation)
- `.agents/skills/auto-kb/SKILL.md` - Skill documentation (updated to reflect automatic invocation)
- `.agents/skills/auto-kb/auto-kb.mjs` - Skill implementation (corrected KB path from chaba-yomi to chaba)
- `.windsurf/workflows/auto-kb-creation.md` - Workflow documentation (updated to reflect implemented status)

## Usage/Commands

```bash
# Auto-kb is automatically invoked by assistant at end of sessions
# No manual invocation required for standard KB processing

# For major new topics during work, assistant will:
# 1. Suggest KB entry creation
# 2. Ask for user confirmation
# 3. Use auto-kb skill for processing
```

## Troubleshooting

### Auto-kb not invoked automatically
- Check `.windsurfrules` for KB processing rules
- Verify KB review section was appended to response
- Ensure content contains KB-worthy triggers

### Incorrect KB path in auto-kb.mjs
- Verify KB_DIR constant points to `/home/tony/CascadeProjects/chaba/docs/kb/`
- Previous incorrect path: `/home/tony/CascadeProjects/chaba-yomi/docs/kb/`

### Redundancy detection not working
- Check that KB directory exists and is accessible
- Verify existing KB entries are readable
- Review overlap threshold in checkRedundancy function

## Related Documentation

- **[auto-kb-creation.md](../../.windsurf/workflows/auto-kb-creation.md)** - Detailed workflow documentation
- **[.windsurfrules](../../.windsurfrules)** - Mandatory KB processing rules

## Tags

- **kb-workflow**: Knowledge base entry creation and management
- **automation**: Automated assistant workflows
- **skill**: Agent skill implementation
- **quality-control**: Redundancy checking and entry quality
