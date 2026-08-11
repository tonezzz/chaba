# workflows-mcp Integration

## What it is

YAML-based workflow orchestration and automation system for Chaba infrastructure using workflows-mcp server. Provides unified automation layer for defining and executing complex multi-step tasks through YAML workflow definitions with dependency-aware execution, interactive prompts, and async job management.

## Context/Background

Integrated on 2026-08-10 to enhance automation capabilities beyond standalone cron scripts. Replaces script-based automation with YAML workflow orchestration that integrates with existing MCP servers (GPU, GitHub, PostgreSQL, Yomi, etc.) and provides better maintainability and composability.

## Key Details

### Technical Details
- **Installation Method**: pipx with MCP 2.0 compatibility fix
- **MCP Compatibility**: Requires `mcp<2.0.0` due to `mcp.server.fastmcp` module removal in MCP 2.0
- **Workflow Directory**: `/home/tony/CascadeProjects/chaba/workflows/`
- **MCP Configuration**: Added to `/home/tony/.config/devin/mcp_config.json`
- **Environment Variables**: `WORKFLOWS_TEMPLATE_PATHS`, `WORKFLOWS_LOG_LEVEL`

### Installation Commands
```bash
# Install workflows-mcp
pipx install workflows-mcp

# Fix MCP 2.0 compatibility
pipx inject workflows-mcp "mcp<2.0.0" --force

# Verify installation
workflows-mcp --help
```

### MCP Configuration
```json
{
  "mcpServers": {
    "workflows": {
      "command": "workflows-mcp",
      "env": {
        "WORKFLOWS_TEMPLATE_PATHS": "/home/tony/CascadeProjects/chaba/workflows",
        "WORKFLOWS_LOG_LEVEL": "INFO"
      }
    }
  }
}
```

### Workflow Directory Structure
```
/home/tony/CascadeProjects/chaba/workflows/
├── automation/       # General automation workflows
├── maintenance/      # System maintenance workflows
├── monitoring/       # Health monitoring workflows
└── interactive/      # Interactive workflows with user prompts
```

### Valid Data Types
- `str` - String values
- `num` - Numeric values (not `int`)
- `bool` - Boolean values
- `list` - Array values
- `dict` - Object values

### Block Types
- **Shell**: Execute shell commands
- **Http**: Make HTTP requests
- **Log**: Log messages (use Shell instead - Log block not supported)
- **Prompt**: Interactive user prompts
- **RenderTemplate**: Template rendering
- **Workflow**: Call other workflows

### Output Access Patterns
Shell block outputs:
- `blocks.{id}.outputs.stdout` - Standard output
- `blocks.{id}.outputs.stderr` - Standard error
- `blocks.{id}.outputs.exit_code` - Exit code

## Implementation

### GPU Monitoring Workflow Conversion
Converted `scripts/gpu-monitor.mjs` to YAML workflow (`workflows/monitoring/gpu-health-check.yml` with:
- Configurable thresholds (VRAM, temperature)
- Historical statistics (24h data)
- Alert generation
- JSON output for programmatic consumption

### Universal Health Check Workflow
Created comprehensive health check (`workflows/monitoring/universal-health-check.yml`) with:
- Automatic profile detection (home/mobile)
- Parallel execution for efficiency
- Structured JSON output with health scoring
- Profile-aware service selection
- Container checks only for home profile

### System Maintenance Workflow
Converted `scripts/system-maintenance.mjs` to YAML workflow (`workflows/maintenance/system-cleanup.yml`) with:
- Configurable cleanup options (Docker, journal, logs)
- Disk monitoring with threshold alerts
- Docker health checks
- GPU monitoring integration
- Structured logging and JSON reports

### Performance Optimization
- **Block Consolidation**: Reduced universal health check from 6 blocks to 4 blocks (33% reduction)
- **Parallel Execution**: Service checks run in parallel (~0.14s for 5 services vs ~3s sequential)
- **Profile-Aware Defaults**: Home (5s timeout, container checks), Mobile (10s timeout, no container checks)
- **Smart Service Selection**: Optional services can be skipped for faster checks

## Usage/Commands

### Execute Workflow
```bash
# Execute registered workflow
mcp_call_tool server_name=workflows tool_name=execute_workflow \
  arguments='{"workflow": "workflow-name", "inputs": {...}}'

# Execute inline workflow (for testing)
mcp_call_tool server_name=workflows tool_name=execute_inline_workflow \
  arguments='{"workflow_yaml": "...", "inputs": {...}}'

# List available workflows
mcp_call_tool server_name=workflows tool_name=list_workflows \
  arguments='{"tags": ["health", "monitoring"]}'

# Get workflow info
mcp_call_tool server_name=workflows tool_name=get_workflow_info \
  arguments='{"workflow": "workflow-name"}'
```

### Example Usage
```bash
# Universal health check with auto profile detection
mcp_call_tool server_name=workflows tool_name=execute_workflow \
  arguments='{"workflow": "universal-health-check", "inputs": {"profile": "auto", "skip_optional": true}}'

# System maintenance with disk threshold
mcp_call_tool server_name=workflows tool_name=execute_workflow \
  arguments='{"workflow": "system-cleanup", "inputs": {"disk_threshold": 85, "docker_prune": true}}'

# GPU health check with custom thresholds
mcp_call_tool server_name=workflows tool_name=execute_workflow \
  arguments='{"workflow": "gpu-health-check", "inputs": {"vram_warning": 75, "temp_warning": 70}}'
```

## Troubleshooting

### ModuleNotFoundError for mcp.server.fastmcp
**Issue**: workflows-mcp requires `mcp<2.0.0` due to module removal in MCP 2.0
**Solution**: `pipx inject workflows-mcp "mcp<2.0.0" --force`

### Workflow Not Found
**Issue**: Workflow not appearing in list_workflows()
**Solution**: Check workflow YAML syntax, verify workflow directory path in MCP config

### Variable Resolution Errors
**Issue**: Template variables not resolving correctly
**Solution**: Use correct output access patterns: `blocks.{id}.outputs.stdout`, check block dependencies

### Interactive Workflows Not Responding
**Issue**: Prompt blocks hanging or not getting user input
**Solution**: Use `resume_workflow()` for paused interactive workflows, check job status with `get_job_status()`

### MCP Compatibility Issues
**Issue**: workflows-mcp not starting or import errors
**Solution**: Reinstall with MCP constraint: `pipx reinstall workflows-mcp && pipx inject workflows-mcp "mcp<2.0.0" --force`

## Related Documentation

- **[mcp-tools.md](mcp-tools.md)** - MCP server inventory and configuration
- **[system-automation.md](system-automation.md)** - Existing automation scripts
- **[ssot.mcp.yml](../ssot/infrastructure/ssot.mcp.yml)** - MCP configuration SSOT
- **[ssot.automation.yml](../ssot/infrastructure/ssot.automation.yml)** - Automation SSOT
- **[EFFICIENCY_ANALYSIS.md](../../workflows/EFFICIENCY_ANALYSIS.md)** - Workflow performance analysis

## KB Workflow Integration with mcp-kbman

**Integration Date**: 2026-08-11

**Purpose**: mcp-kbman provides KB workflow compliance that can be integrated with workflows-mcp for automated KB management tasks.

**KB Documentation**: See Personal KB `meta/kb-workflow-integration.md` for complete KB workflow details

### KB Workflow Tools in mcp-kbman

- **Workflow Start**: `kb_workflow_start()` - Complete workflow check before work
- **Workflow End**: `kb_workflow_end(summary)` - Commit changes and update changelog
- **Git Operations**: `kb_git_status()`, `kb_git_diff()`, `kb_git_commit()`
- **Duplicate Detection**: `kb_check_duplicates()` - Detect GDrive naming conflicts
- **Frontmatter Validation**: `kb_validate_frontmatter()` - Ensure proper KB entry format
- **Session Management**: `kb_read_current_context()`, `kb_update_current_context()`, `kb_read_active_projects()`, `kb_update_active_projects()`

### Example Workflow Integration

Create a KB management workflow in YAML:

```yaml
name: kb-daily-sync
description: Daily KB sync and validation
inputs:
  summary:
    type: str
    description: "Commit summary for the sync"

blocks:
  - id: kb-start
    type: Shell
    command: "cd /home/tony/CascadeProjects/chaba-kbman/mcp-kbman && python3 -c 'from workflow.coordinator import WorkflowCoordinator; coordinator = WorkflowCoordinator(); check = coordinator.kb_start_check(); print(check[\"ready_for_work\"])'"
  
  - id: kb-end
    type: Shell
    command: "cd /home/tony/CascadeProjects/chaba-kbman/mcp-kbman && python3 -c 'from workflow.coordinator import WorkflowCoordinator; coordinator = WorkflowCoordinator(); result = coordinator.kb_end_commit(\"{{inputs.summary}}\"); print(result[\"success\"])'"
```

### Integration Benefits

- **Automated workflow checks**: Ensure KB is ready before automated operations
- **Structured KB management**: Use mcp-kbman tools in workflows for consistent KB operations
- **Error handling**: Leverage mcp-kbman's validation and duplicate detection in workflows
- **Session tracking**: Integrate current-context and active-projects management in workflows

## Tags

- **workflows-mcp**: YAML workflow orchestration system
- **automation**: Task automation and scheduling
- **mcp**: Model Context Protocol integration
- **yaml**: Configuration as code
- **monitoring**: Health check and system monitoring
- **maintenance**: System cleanup and maintenance