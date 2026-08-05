---
description: Automated KB entry creation workflow
---

# Automated KB Entry Creation

## Overview

This workflow automates the creation of KB entries based on KB review sections appended to assistant responses. The goal is to reduce manual overhead while maintaining KB quality and consistency.

## Trigger Conditions

KB entries should be automatically created when:

1. **Significant Bug Fixes**: Especially data corruption, security vulnerabilities, or system-breaking issues
2. **New Patterns/Workarounds**: Discovered solutions to recurring problems
3. **New Systems/Integrations**: Implementation of new technologies or services
4. **Configuration Optimizations**: Performance improvements or infrastructure changes
5. **Language-Specific Issues**: Thai/English mixed content, encoding problems
6. **Root Cause Analyses**: Complex problem investigations and resolutions
7. **Reusable Patterns**: Conventions, templates, or best practices

## KB Entry Template

```markdown
# [Title]

## What it is

[Brief description of what this entry documents]

## Context/Background

[When and why this became relevant - session date, user request, problem encountered]

## Key Details

### Technical Details
- [Specific technical information, configurations, code snippets]

### Implementation
- [How it was implemented or resolved]

### Files/Components
- [Related files, services, or components]

## Usage/Commands

```bash
[Relevant commands or usage examples]
```

## Troubleshooting

### Common Issues
- [Issue 1]: [Solution]
- [Issue 2]: [Solution]

## Related Documentation

- **[Related KB entry]**
- **[Project documentation]**

## Tags

- **[tag1]**: [description]
- **[tag2]**: [description]
```

## Automation Workflow

### Step 1: KB Review Analysis
After each assistant response, analyze the KB review section for:
- KB-worthy triggers (see above)
- Redundancy with existing entries
- Archival opportunities for outdated entries

### Step 2: Redundancy Check
Before creating new entries:
1. Search existing KB entries for overlapping content
2. Update existing entries instead of creating duplicates
3. Archive outdated entries rather than deleting

### Step 3: Entry Creation
If new entry is warranted:
1. Use the KB entry template above
2. Include comprehensive technical details
3. Add code snippets, commands, and configurations
4. Link to related documentation
5. Add relevant tags for discoverability

### Step 4: Entry Location
Place KB entries in: `/home/tony/CascadeProjects/chaba/docs/kb/`

**Note**: Corrected from previous incorrect path `/home/tony/CascadeProjects/chaba-yomi/docs/kb/`

### Step 5: Cross-Reference
Update related KB entries with cross-references if needed.

## Quality Criteria

### KB-Worthy Entry Requirements:
- **Operational Value**: Helps with current or future operations
- **Reusability**: Can be applied to similar situations
- **Prevention**: Helps prevent recurring issues
- **Specificity**: Contains actionable technical details
- **Context**: Includes when/why it's relevant

### Non-KB-Worthy:
- Temporary commands or one-off output
- Obvious trivia or well-known information
- Transient debugging steps without lasting value
- Personal preferences without technical justification

## Existing KB Entries

Reference existing entries for patterns and structure:
- `yomi.md` - Yomi LINE web app comprehensive documentation
- `weaviate.md` - Weaviate vector database setup and troubleshooting
- `h3-pages.md` - H3 page creation workflow
- `health-check.md` - Health check system documentation
- `dependency-management.md` - Dependency management practices

## Integration with Assistant Workflow

### Current Automated Process:
1. Assistant appends KB review section to response (MANDATORY per `.windsurfrules`)
2. Assistant automatically invokes auto-kb skill to process KB review section (MANDATORY per `.windsurfrules`)
3. Auto-kb skill checks redundancy with existing entries
4. Auto-kb skill updates existing entries or creates new ones as needed
5. User can review and modify created entries if desired

### Manual Exception Process:
For major new topics during work (not end-of-session):
1. Assistant suggests KB entry creation when encountering KB-worthy triggers
2. Assistant asks user for confirmation before creating major new entries
3. Assistant uses auto-kb skill for processing to ensure consistency
4. Assistant provides suggested KB entry title and description

## Implementation Status

**✅ IMPLEMENTED**: Auto-kb skill is fully operational and automatically invoked at end of sessions.

### Current Implementation:
- **Skill Location**: `.agents/skills/auto-kb/SKILL.md`
- **Automatic Invocation**: MANDATORY per `.windsurfrules` 
- **Path Configuration**: `/home/tony/CascadeProjects/chaba/docs/kb/`
- **Redundancy Checking**: Built-in to prevent duplicate entries
- **Quality Criteria**: Enforced per skill documentation

### Skill Capabilities:
- Analyzes KB review content for KB-worthiness triggers
- Checks redundancy with existing KB entries
- Updates existing entries instead of creating duplicates
- Archives outdated entries when needed
- Follows consistent KB entry structure and quality criteria

## Example KB Entry Creation

### Input (KB Review Section):
```
KB review: Created daily2 page with calendar layout for Yomi daily summaries. Required web stack restart to pick up new file. Page now accessible at /apps/yomi/daily2/index.html with basic auth. Uses existing API endpoints and follows project styling conventions.
```

### Analysis:
- **KB-Worthy**: Yes (new feature implementation)
- **Redundancy Check**: No existing entry for daily2 page
- **Entry Type**: Feature documentation

### Output (KB Entry):
```markdown
# Yomi Daily2 Calendar Page

## What it is

Calendar-based daily summary viewer for Yomi LINE conversations with date selection and summary display.

## Context/Background

Created 2026-08-04 to provide alternative interface for daily summaries with calendar navigation instead of list view.

## Key Details

### Technical Details
- **Location**: `/home/tony/CascadeProjects/chaba/stacks/web/public/apps/yomi/daily2/index.html`
- **Access**: `http://tony-omen.local:8080/apps/yomi/daily2/index.html`
- **Auth**: Basic auth (same as other Yomi pages)
- **Layout**: Two-panel design (calendar left, summary right)
- **KB Path**: `/home/tony/CascadeProjects/chaba/docs/kb/` (corrected from chaba-yomi)

### Implementation
- Left panel: Monthly calendar with navigation, date selection, visual indicators for dates with summaries
- Right panel: Daily summary display (events, actions, topics, message count)
- Uses existing `/api/yomi/conversations` and `/api/yomi/daily` API endpoints
- Follows project styling conventions from original daily page

### Files/Components
- `stacks/web/public/apps/yomi/daily2/index.html` - Main page
- `stacks/web/Caddyfile` - Caddy configuration (no changes needed)
- `scripts/yomi/yomi-api.mjs` - API endpoints (existing)

## Usage/Commands

```bash
# Access the page
http://tony-omen.local:8080/apps/yomi/daily2/index.html?chat=<chatId>

# Restart web stack if new files not picked up
just -f /home/tony/CascadeProjects/chaba/Justfile restart-web
```

## Troubleshooting

### Page not found (404)
- Restart web stack: `just restart-web`
- Verify file exists: `ls -la stacks/web/public/apps/yomi/daily2/`
- Check Caddy is running: `docker ps | grep web`

### 401 Unauthorized
- Expected behavior - Yomi pages require basic auth
- Use Yomi credentials from environment configuration

## Related Documentation

- **[yomi.md](yomi.md)** - Yomi LINE web app comprehensive documentation
- **[h3-pages.md](h3-pages.md)** - Page creation workflow

## Tags

- **yomi**: LINE conversation management
- **daily-summaries**: Daily summary generation and display
- **calendar**: Date-based navigation interface
- **web-ui**: Static web interface components
```

## Next Steps

1. ✅ Create `auto-kb` skill with automation logic - **COMPLETED**
2. ✅ Implement redundancy checking against existing KB entries - **COMPLETED**
3. ✅ Add quality criteria validation - **COMPLETED**
4. ✅ Test with recent KB review content - **COMPLETED**
5. ✅ Refine based on usage patterns - **COMPLETED**
6. Monitor usage and refine automation quality as needed
7. Consider adding more sophisticated redundancy detection algorithms
