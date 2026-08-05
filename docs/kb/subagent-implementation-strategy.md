# Subagent Implementation Strategy

## What it is

Systematic approach to creating custom subagents for specialized tasks in the Chaba project ecosystem. Subagents provide focused, domain-specific capabilities that can be invoked by the main agent for parallel execution, complex exploration, or background processing.

## Context/Background

Created 2026-08-05 during comprehensive subagent implementation across Chaba and Chaba-Raceman projects. Seven custom subagents were created to handle specialized domains: Yomi processing, cross-project health monitoring, SSOT migration, Weaviate indexing, GPU queue testing, git workflow automation, and documentation updates.

## Key Details

### Subagent Architecture

**Location**: `/home/tony/CascadeProjects/chaba/.devin/agents/`

**File Structure**:
```yaml
---
name: subagent-name
description: Brief description of subagent purpose
model: sonnet  # or other model as appropriate
allowed-tools:
  - read
  - write
  - exec
  - mcp_call_tool
  # ... other tools as needed
---
```

**Implementation Pattern**:
1. Define clear domain-specific responsibilities
2. Specify appropriate tool permissions
3. Provide detailed workflow patterns
4. Include error handling guidelines
5. Document file locations and dependencies
6. Define output format expectations

### Subagent Profiles

**Read-Only Subagents** (for exploration/research):
- Tools: grep, glob, read, web_search
- Purpose: Codebase exploration, research, search without modifications
- Use Cases: Finding patterns, tracing dependencies, impact analysis

**Full-Access Subagents** (for implementation):
- Tools: read, write, edit, exec (and more)
- Purpose: General-purpose tasks requiring write access or command execution
- Use Cases: Multi-step implementation, infrastructure operations, testing

### Created Subagents (2026-08-05)

| Subagent | Purpose | Model | Key Tools |
|----------|---------|-------|-----------|
| yomi-processor | Yomi conversation data processing | sonnet | read, write, exec, mcp_call_tool |
| cross-project-health | Multi-project health monitoring | sonnet | read, exec, grep |
| ssot-migrator | SSOT data migration and validation | sonnet | read, write, exec |
| weaviate-indexer | Weaviate vector indexing operations | sonnet | read, write, exec, mcp_call_tool |
| gpu-queue-tester | GPU queue testing and validation | sonnet | read, exec, write |
| git-workflow | Git workflow automation | sonnet | read, write, exec |
| documentation-updater | Documentation maintenance | sonnet | read, write, exec |
| static-site-tester | E2E test management (raceman) | sonnet | read, exec, write |

### Best Practices

**When to Use Subagents**:
1. **Parallel Execution**: Multiple independent tasks can run simultaneously
2. **Complex Exploration**: Broad, uncertain searches across codebases
3. **Multi-Step Tasks**: Self-contained work with many interdependent steps
4. **Context Isolation**: Work unrelated to current task to keep context clean
5. **Background Processing**: Long-running tasks while continuing other work

**When NOT to Use Subagents**:
1. **Single Operations**: One-off file reads, simple edits, single commands
2. **Known Paths**: When you already know the exact file or function location
3. **Simple Questions**: Quick answers you can provide directly
4. **Sequential Dependencies**: Tasks that must run in order (chain in one agent)
5. **Overhead-Heavy**: Tasks where sub-agent setup cost exceeds benefit

### Front-Loading Context

Subagents are stateless and cannot ask clarifying questions. Always provide:
- Relevant file paths and directories
- Function/class names to investigate
- Existing patterns to follow
- Project-specific conventions
- Exactly what you need back

### Communication Patterns

**Good Delegation Example**:
```
"Investigate the error handling patterns in the API layer.
Look at src/api/ directory, focusing on middleware and route handlers.
I need to understand how errors are caught, logged, and returned to clients.
This is research only - do not make any changes.
Be thorough - check all API-related files."
```

**Bad Delegation Example**:
```
"Look at the API code and tell me about it."
```
(Too vague, no scope, no specific goal)

### Parallel Execution Strategy

- Launch background sub-agents in parallel for independent tasks
- Use foreground sub-agents when sequential work is needed
- Don't launch multiple foreground sub-agents simultaneously
- Launch background sub-agents first, then foreground if needed

### Verification After Sub-Agent Work

1. **Review Changes**: Check for consistency with project patterns
2. **Run Verification**: Tests, lint, typecheck, build as appropriate
3. **Test Functionality**: Verify the changes work as expected
4. **Update Documentation**: Update docs if behavior changed
5. **Commit Changes**: Use proper commit messages

## Usage/Commands

```bash
# Subagent invocation is handled by the main agent
# No manual invocation required for standard operations

# Subagent configuration files are located in:
/home/tony/CascadeProjects/chaba/.devin/agents/

# Skills (reusable agent capabilities) are located in:
/home/tony/CascadeProjects/chaba/.agents/skills/
```

## Troubleshooting

### Subagent not following instructions
- Check that context was front-loaded with specific requirements
- Verify task scope is clearly defined
- Ensure allowed-tools include necessary capabilities
- Review subagent definition for clarity

### Parallel execution issues
- Ensure tasks are truly independent
- Check for shared resource conflicts
- Verify background vs foreground usage is appropriate
- Review shell_id management for background processes

### Context loss in subagents
- Subagents are stateless - cannot maintain context between calls
- Front-load all necessary information in initial request
- Provide complete file paths and dependencies
- Include error handling patterns in instructions

## Related Documentation

- **[.windsurfrules](../../.windsurfrules)** - Global sub-agent usage guidelines
- **[auto-kb-workflow.md](auto-kb-workflow.md)** - Automated KB processing skill
- **[dependency-management.md](dependency-management.md)** - Dependency system using subagents

## Tags

- **subagent**: Custom agent implementation
- **automation**: Agent workflow patterns
- **parallel-execution**: Concurrent task processing
- **domain-specific**: Specialized agent capabilities
- **best-practices**: Implementation guidelines
