---
category: operations
---

# Key Details

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

