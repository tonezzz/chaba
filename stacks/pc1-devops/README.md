# PC1 DevOps Stack

Dedicated stack for DevOps workflows, automation, and development operations.

## Services

- **mcp-devops** - Development workflows and automation
  - Port: 8325
  - Features: Docker operations, workflow management, deployment automation
  - Access: Docker socket, workspace mounting

## Usage

```bash
# Start DevOps stack
docker-compose --file docker-compose.yml up -d

# Check health
curl http://localhost:8325/health

# Test workflow listing
curl -X POST http://localhost:8325/invoke \
  -H "Content-Type: application/json" \
  -d '{"tool":"list_workflows","arguments":{}}'
```

## Cross-Host Access

The DevOps service is designed to be accessible from other hosts:

### From pc2-worker or other hosts
```json
// 1mcp.json configuration
{
  "mcpServers": {
    "pc1-mcp-devops": {
      "transport": "streamableHttp",
      "url": "http://pc1.vpn:8325/mcp",
      "tags": ["pc1", "devops", "automation", "remote"],
      "enabled": true
    }
  }
}
```

### Environment Setup
```bash
# Copy environment file
cp .env.example .env

# Adjust configuration as needed
# PC1_WORKSPACE_HOST_DIR=C:/chaba
# MCP_DEVOPS_PORT=8325
```

## Network

- **Network**: `pc1-devops-net` (172.22.0.0/16)
- **VPN Access**: Available via `pc1.vpn:8325`
- **Docker Access**: Direct socket mounting

## Features

### Workflow Management
- **List Workflows**: Discover available development workflows
- **Run Workflows**: Execute preview, publish, and deployment workflows
- **Dry Run**: Preview workflow commands before execution
- **Status Tracking**: Monitor workflow progress and results

### Development Operations
- **Docker Integration**: Direct Docker daemon access
- **Workspace Mounting**: Full repository access
- **Multi-stack Support**: Manage multiple stack deployments
- **Health Monitoring**: Service and infrastructure health checks

### MCP Tools
- `list_workflows` - List available development workflows
- `run_workflow` - Execute specific workflow with parameters
- `system_telemetry` - Collect system diagnostics
- `deploy_pc1_stack` - Deploy pc1-stack with testing
- `publish_pc1_stack` - Publish with rollback capability

## Requirements

- Docker with socket access
- Sufficient workspace storage
- Network access to other stacks/services
- Appropriate permissions for container operations

## Security Considerations

- **Docker Socket**: Full container management access
- **Workspace Access**: Complete repository access
- **Network Access**: Can reach other services
- **Recommendation**: Use in trusted environments only

## Integration

This stack integrates with:
- **pc1-stack** - Main MCP services deployment
- **pc1-gpu** - GPU service management
- **pc1-deka** - Legal scraping workflows
- **pc2-worker** - Remote development operations
