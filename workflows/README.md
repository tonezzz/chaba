# Chaba Workflows

YAML-based workflow orchestration using workflows-mcp for automation, monitoring, and maintenance tasks.

## Directory Structure

```
workflows/
├── automation/          # General automation workflows
│   └── example-workflow.yml
├── maintenance/         # System maintenance workflows
│   └── system-cleanup.yml
├── monitoring/          # Health monitoring workflows
│   ├── gpu-health-check.yml
│   ├── home-profile-health-check.yml
│   └── universal-health-check.yml
├── interactive/         # Interactive workflows with user prompts
│   └── confirm-maintenance.yml
├── efficiency-test.yml  # Workflow performance testing
└── README.md           # This file
```

## Workflow Categories

### Automation
General automation workflows for common tasks.

**Example Workflow:** Basic template for automation tasks
- Input validation
- Shell command execution
- Error handling
- Output formatting

### Maintenance
System maintenance and cleanup workflows.

**System Cleanup:** Comprehensive system maintenance
- Docker cleanup (images, containers, volumes, cache)
- Journal log cleanup (limit to 500M)
- System log cleanup (>30 days)
- Disk space monitoring with alerts
- Docker container health checks
- GPU monitoring integration

### Monitoring
Health monitoring and service checks.

**GPU Health Check:** GPU monitoring with thresholds
- VRAM usage monitoring (warning: 80%, critical: 90%)
- Temperature monitoring (warning: 75°C, critical: 85°C)
- Historical statistics (24h data)
- Alert generation
- JSON output for programmatic consumption

**Home Profile Health Check:** Home network service monitoring
- 16 services across web, API, data, queue, GPU categories
- 192.168.1.52 base URL
- 5s timeout for local network
- Container health checks
- Optional service filtering

**Universal Health Check:** Auto-detecting health check
- Automatic profile detection (home/mobile)
- Parallel execution for efficiency
- Profile-aware service selection
- Structured JSON output with health scoring
- Container checks only for home profile

### Interactive
Workflows requiring user interaction and confirmation.

**Confirm Maintenance:** Interactive maintenance workflow
- User prompts for confirmation
- Pause/resume capabilities
- Conditional execution based on user input

## Usage

### Execute Workflow

```bash
# Using MCP server
mcp_call_tool server_name=workflows tool_name=execute_workflow \
  arguments='{"workflow": "workflow-name", "inputs": {...}}'

# Execute inline workflow (for testing)
mcp_call_tool server_name=workflows tool_name=execute_inline_workflow \
  arguments='{"workflow_yaml": "...", "inputs": {...}}'
```

### List Available Workflows

```bash
mcp_call_tool server_name=workflows tool_name=list_workflows \
  arguments='{"tags": ["health", "monitoring"]}'
```

### Get Workflow Information

```bash
mcp_call_tool server_name=workflows tool_name=get_workflow_info \
  arguments='{"workflow": "workflow-name"}'
```

## Workflow Syntax

### Basic Structure

```yaml
name: workflow-name
description: Workflow description
version: "1.0"
author: Author Name
tags: [tag1, tag2, tag3]

inputs:
  input_name:
    type: str|num|bool|list|dict
    description: Input description
    default: default_value
    required: false

blocks:
  - id: block_id
    type: Shell|Http|Prompt
    description: Block description
    inputs:
      command: "shell command"
      timeout: 30
    depends_on:
      - previous_block_id

outputs:
  output_name:
    value: "{{blocks.block_id.outputs.stdout}}"
```

### Valid Data Types
- `str` - String values
- `num` - Numeric values
- `bool` - Boolean values
- `list` - Array values
- `dict` - Object values

### Block Types
- **Shell**: Execute shell commands
- **Http**: Make HTTP requests
- **Prompt**: Interactive user prompts
- **RenderTemplate**: Template rendering
- **Workflow**: Call other workflows

### Output Access
- `blocks.{id}.outputs.stdout` - Standard output
- `blocks.{id}.outputs.stderr` - Standard error
- `blocks.{id}.outputs.exit_code` - Exit code

## Examples

### Universal Health Check

```bash
mcp_call_tool server_name=workflows tool_name=execute_workflow \
  arguments='{"workflow": "universal-health-check", "inputs": {"profile": "auto", "skip_optional": true}}'
```

### System Maintenance

```bash
mcp_call_tool server_name=workflows tool_name=execute_workflow \
  arguments='{"workflow": "system-cleanup", "inputs": {"disk_threshold": 85, "docker_prune": true}}'
```

### GPU Health Check

```bash
mcp_call_tool server_name=workflows tool_name=execute_workflow \
  arguments='{"workflow": "gpu-health-check", "inputs": {"vram_warning": 75, "temp_warning": 70}}'
```

## Performance

### Execution Times
- **GPU Health Check**: ~0.1s overhead (24% increase over direct script)
- **Universal Health Check**: ~0.14s for 5 services (parallel execution)
- **System Maintenance**: Variable (1-5 minutes depending on cleanup operations)

### Optimization Techniques
- **Parallel Execution**: Independent blocks run concurrently
- **Profile-Aware Defaults**: Optimized timeouts for network conditions
- **Smart Service Selection**: Optional services can be skipped
- **Block Consolidation**: Reduced block count for efficiency

## Configuration

### MCP Configuration
```json
{
  "mcpServers": {
    "workflows": {
      "command": "workflows-mcp",
      "env": {
        "WORKFLOWS_TEMPLATE_PATHS": "/home/tony/CascadeProjects/chaba-tony-dell/workflows",
        "WORKFLOWS_LOG_LEVEL": "INFO"
      }
    }
  }
}
```

### Environment Variables
- `WORKFLOWS_TEMPLATE_PATHS`: Path to workflow directory
- `WORKFLOWS_LOG_LEVEL`: Logging level (DEBUG, INFO, WARNING, ERROR)

## Troubleshooting

### Common Issues

**ModuleNotFoundError for mcp.server.fastmcp**
- **Solution**: `pipx inject workflows-mcp "mcp<2.0.0" --force`

**Workflow Not Found**
- **Solution**: Check workflow YAML syntax, verify workflow directory path in MCP config

**Variable Resolution Errors**
- **Solution**: Use correct output access patterns: `blocks.{id}.outputs.stdout`

**Interactive Workflows Not Responding**
- **Solution**: Use `resume_workflow()` for paused workflows, check job status

## Related Documentation

- **[workflows-mcp-integration.md](../docs/kb/workflows-mcp-integration.md)** - Comprehensive integration guide
- **[system-automation.md](../docs/kb/system-automation.md)** - Existing automation scripts
- **[ssot.automation.yml](../docs/ssot/infrastructure/ssot.automation.yml)** - Automation SSOT
- **[EFFICIENCY_ANALYSIS.md](./EFFICIENCY_ANALYSIS.md)** - Performance analysis

## Development

### Creating New Workflows

1. **Choose Category**: Place in appropriate directory (automation/, maintenance/, monitoring/, interactive/)
2. **Follow Template**: Use existing workflows as templates
3. **Test Locally**: Use `execute_inline_workflow` for testing
4. **Add Documentation**: Update this README with workflow details
5. **Update SSOT**: Add to `ssot.automation.yml` if relevant

### Best Practices

- **Descriptive Names**: Use clear, descriptive workflow and block names
- **Error Handling**: Include proper error handling and logging
- **Timeouts**: Set appropriate timeouts for each block
- **Dependencies**: Use `depends_on` for block ordering
- **Documentation**: Add comprehensive descriptions and examples

## Maintenance

### Regular Tasks
- Review workflow performance and optimize bottlenecks
- Update workflows to match infrastructure changes
- Test workflows after system updates
- Clean up unused or outdated workflows

### Monitoring
- Monitor workflow execution logs
- Track workflow performance metrics
- Review workflow failure rates
- Update workflows based on monitoring insights

## Status

**Last Updated**: 2026-08-10
**Total Workflows**: 7 custom workflows + 34 built-in workflows
**Status**: Operational and tested