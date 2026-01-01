# IDC1 Modular Stack Structure

This directory contains the core IDC1 stack services. The original monolithic `idc1-stack` has been reorganized into modular components following the same pattern as `pc1-stack` and `pc2-worker`.

## Stack Architecture

### Core Stack (this directory)
- **1mcp-agent**: MCP aggregation service
- **mcp-agents**: Agents observability and session management  
- **mcp-glama**: Glama AI model gateway

### Supporting Stacks

#### `idc1-db/` - Data & RAG Services
- **ollama**: Local LLM inference server
- **qdrant**: Vector database for embeddings
- **mcp-rag**: RAG (Retrieval-Augmented Generation) service
- **mcp-memory**: Persistent memory storage

#### `idc1-web/` - User Interfaces
- **code-server**: VS Code in the browser
- **webtops-router**: Webtop session router
- **mcp-webtops**: Webtop session management
- **webtops-cp**: Webtop control panel

#### `idc1-devops/` - Development Tools
- **mcp-devops**: DevOps automation and workflows
- **mcp-tester**: MCP service testing framework
- **mcp-playwright**: Browser automation and testing

#### `idc1-line/` - LINE Integration
- **mcp-line**: LINE webhook and messaging service

## Quick Start

### 1. Migration from Original Stack
```bash
# Backup existing configuration
./scripts/migrate-idc1-stacks.ps1 -Force

# Create environment files
cp stacks/idc1-db/.env.example stacks/idc1-db/.env
cp stacks/idc1-web/.env.example stacks/idc1-web/.env
cp stacks/idc1-devops/.env.example stacks/idc1-devops/.env
cp stacks/idc1-line/.env.example stacks/idc1-line/.env
```

### 2. Start All Stacks
```bash
# Start all stacks in dependency order
./scripts/start-idc1-stacks.ps1

# Or start specific stacks
./scripts/start-idc1-stacks.ps1 -Stacks core,db,web
```

### 3. Check Status
```bash
./scripts/start-idc1-stacks.ps1 -Status
```

### 4. View Logs
```bash
# All logs
./scripts/start-idc1-stacks.ps1 -Logs

# Specific stack logs
./scripts/start-idc1-stacks.ps1 -Logs -Stacks core,db
```

## Port Allocation

| Stack | Service | Port | Description |
|-------|---------|------|-------------|
| core | 1mcp-agent | 3050 | MCP aggregation |
| core | mcp-agents | 8446 | Agents API |
| core | mcp-glama | 7441 | Glama gateway |
| db | ollama | 11434 | LLM inference |
| db | qdrant | 6333 | Vector database |
| db | mcp-rag | 8455 | RAG service |
| db | mcp-memory | 8470 | Memory storage |
| web | code-server | 8080 | VS Code web |
| web | webtops-router | 3001 | Webtop router |
| web | mcp-webtops | 8091 | Webtop management |
| web | webtops-cp | 3005 | Control panel |
| devops | mcp-devops | 8425 | DevOps automation |
| devops | mcp-tester | 8435 | Testing framework |
| devops | mcp-playwright | 8460 | Browser automation |
| line | mcp-line | 8088 | LINE webhook |

## Network Architecture

All stacks share external networks for inter-stack communication:
- `idc1-stack-net`: Core stack network
- `idc1-db-net`: Database services network  
- `idc1-web-net`: Web services network
- `idc1-devops-net`: DevOps tools network
- `idc1-line-net`: LINE service network

## Environment Variables

Each stack has its own `.env.example` file. Key variables to configure:

### Core Stack
- `ONE_MCP_PORT`: MCP aggregation port (default: 3050)
- `MCP_AGENTS_PORT`: Agents API port (default: 8446)
- `MCP_GLAMA_PORT`: Glama gateway port (default: 7441)
- `GLAMA_API_KEY`: Glama API key (required)

### Database Stack
- `OLLAMA_PORT`: Ollama server port (default: 11434)
- `QDRANT_PORT`: Qdrant port (default: 6333)
- `MCP_RAG_PORT`: RAG service port (default: 8455)

### Web Stack
- `CODE_SERVER_PORT`: Code server port (default: 8080)
- `WEBTOPS_ROUTER_PORT`: Webtop router port (default: 3001)
- `WEBTOPS_ADMIN_TOKEN`: Webtop admin token (required)

### DevOps Stack
- `MCP_DEVOPS_PORT`: DevOps service port (default: 8425)
- `MCP_TESTER_PORT`: Tester service port (default: 8435)
- `MCP_PLAYWRIGHT_PORT`: Playwright service port (default: 8460)

### LINE Stack
- `MCP_LINE_PORT`: LINE service port (default: 8088)
- `LINE_CHANNEL_SECRET`: LINE channel secret (required)
- `LINE_CHANNEL_ACCESS_TOKEN`: LINE access token (required)

## Migration Notes

### What Changed
- **Monolithic → Modular**: Single `docker-compose.yml` split into focused stacks
- **Service Isolation**: Related services grouped by function
- **Selective Startup**: Start only needed stacks
- **Consistent Patterns**: Matches pc1/pc2 stack organization

### What Preserved
- **Port Numbers**: All original ports maintained
- **Data Volumes**: Volume names and paths unchanged
- **Environment Variables**: Same configuration options
- **Service Configurations**: Identical service definitions

### Rollback
If needed, rollback using the backup created during migration:
```bash
# Restore original configuration
cp backup-*/docker-compose.original.yml stacks/idc1-stack/docker-compose.yml
cp backup-*/.env.original.example stacks/idc1-stack/.env.example
```

## Development

### Adding New Services
1. Choose appropriate stack based on service function
2. Add service to that stack's `docker-compose.yml`
3. Update environment variables in `.env.example`
4. Update this README with port information

### Cross-Stack Communication
Services can communicate across stacks using service names:
```yaml
# Example: mcp-devops accessing mcp-rag
environment:
  RAG_URL: http://mcp-rag.idc1-db-net:8055
```

## Troubleshooting

### Common Issues
1. **Network conflicts**: Ensure shared networks are created
2. **Port conflicts**: Check port allocation table above
3. **Missing .env files**: Copy from `.env.example` templates
4. **Volume issues**: Verify volume names match original stack

### Health Checks
All services include health checks. Monitor with:
```bash
docker ps --format "table {{.Names}}\t{{.Status}}"
```

### Logs
View logs for specific stacks:
```bash
cd stacks/idc1-db && docker-compose logs -f
```

## Support

For issues with:
- **Migration**: Use `./scripts/migrate-idc1-stacks.ps1 -DryRun` to preview
- **Startup**: Use `./scripts/start-idc1-stacks.ps1 -Status` to check
- **Configuration**: Review individual stack `.env.example` files
