---
category: operations
---

# Implementation

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
