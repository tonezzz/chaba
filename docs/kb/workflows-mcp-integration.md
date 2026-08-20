---
category: operations
---

# workflows-mcp Integration

## What it is

YAML-based workflow orchestration and automation system for Chaba infrastructure using workflows-mcp server. Provides unified automation layer for defining and executing complex multi-step tasks through YAML workflow definitions with dependency-aware execution, interactive prompts, and async job management.

## Context/Background

Integrated on 2026-08-10 to enhance automation capabilities beyond standalone cron scripts. Replaces script-based automation with YAML workflow orchestration that integrates with existing MCP servers (GPU, GitHub, PostgreSQL, Yomi, etc.) and provides better maintainability and composability.

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

## Tags

- **workflows-mcp**: YAML workflow orchestration system
- **automation**: Task automation and scheduling
- **mcp**: Model Context Protocol integration
- **yaml**: Configuration as code
- **monitoring**: Health check and system monitoring
- **maintenance**: System cleanup and maintenance

## See also

- [Workflows Mcp Integration Health](workflows-mcp-integration-health.md)
- [Workflows Mcp Integration Implementation](workflows-mcp-integration-implementation.md)
- [Workflows Mcp Integration Kb](workflows-mcp-integration-kb.md)
- [Workflows Mcp Integration Key Details](workflows-mcp-integration-key-details.md)
