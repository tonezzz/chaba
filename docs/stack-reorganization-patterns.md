# Stack Reorganization Patterns

This document captures lessons learned from reorganizing monolithic stacks into modular structures, specifically from the idc1-stacks work.

## 🎯 Core Principles

### 1. **Functional Separation**
Group services by their primary function:
- **Core**: Essential MCP aggregation services
- **AI**: Machine learning and inference workloads
- **DB**: Data storage and retrieval services
- **Web**: User interfaces and web services
- **DevOps**: Development and testing tools
- **Line**: Host-specific integrations

### 2. **Cross-Stack Communication**
Use external networks with consistent naming:
```
{stack}-{host}-net
Examples:
- idc1-ai-net
- idc1-db-net
- pc1-web-net
```

Service communication pattern:
```yaml
environment:
  EXTERNAL_SERVICE_URL: http://service.{target-stack}-{host}-net:port
```

### 3. **Port Allocation Strategy**
Maintain host-specific port ranges:
- **idc1**: 84xx (MCP), 11xxx (AI), 64xx (DB), 30xx (Web)
- **pc1**: 80xx/82xx (MCP), 30xx (Web)
- **pc2**: 72xx/80xx (MCP), 30xx (Web)

## 🏗️ Architecture Patterns

### Modular Stack Structure
```
stacks/
├── {host}-stack/          # Core services only
├── {host}-{function}/     # Specialized stacks
│   ├── {host}-ai/
│   ├── {host}-db/
│   ├── {host}-web/
│   ├── {host}-devops/
│   └── {host}-{specific}/ # Host-specific services
```

### Service Distribution Rules

1. **Core Stack** (`{host}-stack/`):
   - MCP aggregation (1mcp-agent)
   - Core MCP services (mcp-agents, mcp-glama)
   - Essential for basic functionality

2. **AI Stack** (`{host}-ai/`):
   - Inference servers (ollama)
   - Model serving endpoints
   - GPU-accelerated services
   - Future: text generation, image generation

3. **DB Stack** (`{host}-db/`):
   - Vector databases (qdrant)
   - RAG services (mcp-rag)
   - Memory services (mcp-memory)
   - External AI dependencies

4. **Web Stack** (`{host}-web/`):
   - User interfaces (webtops)
   - Development environments (code-server if needed)
   - Web-based tools

5. **DevOps Stack** (`{host}-devops/`):
   - Testing frameworks (mcp-tester)
   - Automation tools (mcp-devops)
   - Browser automation (mcp-playwright)

6. **Host-Specific Stacks**:
   - Unique integrations (mcp-line for idc1)
   - Authentication (authentik for pc1)
   - Specialized tools

## 🔄 Migration Strategy

### Phase 1: Analysis
1. Inventory existing services
2. Group by function
3. Identify dependencies
4. Plan port allocation

### Phase 2: Preparation
1. Create templates
2. Develop host-agnostic scripts
3. Backup existing configuration
4. Create shared networks

### Phase 3: Implementation
1. Create new stack directories
2. Move services to appropriate stacks
3. Update cross-stack references
4. Test communication

### Phase 4: Validation
1. Start stacks in dependency order
2. Verify service health
3. Test cross-stack communication
4. Monitor resource usage

## 📋 Template System

### File Templates
- `templates/stack-template.yml`: Base docker-compose structure
- `templates/env-template.example`: Environment variable template
- `templates/README-template.md`: Documentation template

### Script Templates
- `scripts/reorganize-stacks.ps1`: Host-agnostic reorganization
- `scripts/start-{host}-stacks.ps1`: Host-specific startup
- `scripts/migrate-{host}-stacks.ps1`: Migration automation

## 🛠️ Cross-Stack Dependencies

### Dependency Management
```yaml
# Example: mcp-rag depending on external ollama
services:
  mcp-rag:
    environment:
      OLLAMA_URL: http://ollama.idc1-ai-net:11434
    depends_on:
      - qdrant  # Internal dependency
    # External dependency (ollama) handled by network
```

### Startup Order
1. **Core** → **AI** → **DB** → **Web** → **DevOps** → **Specific**
2. Use startup scripts that respect dependencies
3. Health checks ensure services are ready

## 🔧 Configuration Patterns

### Environment Variables
```bash
# Service-specific
SERVICE_BUILD_CONTEXT=../../mcp/mcp-service
SERVICE_PORT=8080

# External dependencies  
EXTERNAL_SERVICE_URL=http://service.target-host-net:port

# Cross-stack networking
SERVICE_NETWORK={stack}-{host}-net
```

### Volume Management
- Use descriptive names: `{host}-{stack}-{service}-data`
- Preserve data during migration
- Document volume purposes

## 🚀 Operational Considerations

### Selective Startup
```bash
# Start only needed stacks
./scripts/start-idc1-stacks.ps1 -Stacks core,ai,db

# Check status
./scripts/start-idc1-stacks.ps1 -Status

# View logs
./scripts/start-idc1-stacks.ps1 -Logs -Stacks ai,db
```

### Monitoring
- Health checks on all services
- Cross-stack connectivity tests
- Resource usage per stack
- Log aggregation per stack

### Troubleshooting
1. Check network connectivity: `docker network ls`
2. Verify service discovery: `nslookup service.stack-net`
3. Check dependencies: `docker-compose ps`
4. Review logs: `docker-compose logs -f`

## 📚 Future Enhancements

### Scalability
- Horizontal scaling within stacks
- Load balancing for web services
- Resource quotas per stack

### Automation
- CI/CD for stack updates
- Automated testing of cross-stack communication
- Configuration validation

### Observability
- Metrics per stack
- Distributed tracing
- Centralized logging

## 🎯 Success Metrics

- ✅ Services can start independently
- ✅ Cross-stack communication works
- ✅ Resource isolation is effective
- ✅ Migration is reversible
- ✅ Documentation is complete
- ✅ Templates are reusable

---

*This document evolves as we learn from each host reorganization. Update with new patterns and lessons learned.*
