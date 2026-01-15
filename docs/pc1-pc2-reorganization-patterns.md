# PC1 & PC2 Reorganization Patterns

This document captures the specific patterns and considerations for reorganizing PC1 and PC2 stacks, building on the general patterns learned from idc1.

## 🎯 Host-Specific Characteristics

### PC1 (Production/Development Host)
- **Purpose**: Primary development and production environment
- **Key Features**: Authentication (Authentik), webtops, visualization tools
- **Port Range**: 80xx/82xx (MCP), 30xx (Web), 90xx (Auth)
- **Special Requirements**: External Redis/PostgreSQL dependencies

### PC2 (Windows Worker Host)  
- **Purpose**: Windows-based development and specialized services
- **Key Features**: Thai language processing, meeting transcription, AI4Thai integration
- **Port Range**: 72xx/80xx (MCP), 30xx (Web), 62xx (Specialized)
- **Special Requirements**: Cross-platform development, Thai language support

## 🏗️ PC1 Modular Structure

### Stack Distribution

```
pc1-stack/          # Core MCP services
├── 1mcp-agent      # MCP aggregation
├── mcp-agents      # Agents management  
├── mcp-rag         # RAG services (legacy-db)
├── mcp-tester      # Testing framework
├── mcp-playwright  # Browser automation
└── mcp-http        # HTTP gateway

pc1-auth/           # Authentication services
├── authentik-server
└── authentik-worker

pc1-web/            # Web interfaces
├── webtop2         # Linux desktop environment
└── mcp-webtop      # Webtop management

pc1-devops/         # Development tools
├── mcp-devops       # DevOps automation
└── mcp-quickchart  # Chart generation
```

### PC1-Specific Patterns

#### External Dependencies
```yaml
# Authentik relies on external services
environment:
  AUTHENTIK_REDIS__HOST: pc1.vpn
  AUTHENTIK_POSTGRESQL__HOST: pc1.vpn
```

#### Webtop Integration
```yaml
# mcp-webtop mounts webtop2 config for management
volumes:
  - webtop2-config:/webtop-config:ro
```

#### Profile-Based Services
```yaml
# Core services use profiles for selective startup
services:
  1mcp-agent:
    profiles: ["mcp-suite"]
  authentik-server:
    profiles: ["authentik"]
```

## 🏗️ PC2 Modular Structure

### Stack Distribution

```
pc2-core/           # Runtime environments
├── node-runner     # Node.js development
├── python-runner   # Python development
├── redis           # Caching
└── dev-proxy       # Development proxy

pc2-tools/          # MCP tools
├── mcp-docker      # Docker management
├── mcp-glama       # AI gateway
└── mcp-devops      # DevOps automation

pc2-web/            # Web interfaces
├── webtops-router  # Session router
├── mcp-webtops     # Webtop management
└── webtops-cp      # Control panel

pc2-devops/         # Testing and specialized tools
├── mcp-tester      # Testing framework
├── mcp-agents      # Agents management
├── mcp-playwright  # Browser automation
├── mcp-instrans    # Thai speech-to-text
├── mcp-meeting     # Meeting transcription
└── mcp-vaja        # Thai language processing
```

### PC2-Specific Patterns

#### Thai Language Services
```yaml
# AI4Thai integration for Thai language processing
environment:
  AI4THAI_API_KEY: ${AI4THAI_API_KEY:-}
  VAJA_ENDPOINT: https://api.aiforthai.in.th/vaja
  INSTRANS_DEFAULT_LANG: th
```

#### Cross-Platform Development
```yaml
# Support for both Linux and Windows development
volumes:
  - /var/run/docker.sock:/var/run/docker.sock
  - /mnt/wsl/docker-desktop/run/docker.sock:/var/run/docker-desktop.sock:ro
```

#### Specialized Audio Processing
```yaml
# Meeting transcription with audio storage
environment:
  MEETING_STORAGE_PATH: /data/meetings.json
volumes:
  - ${MEETING_STORAGE_ROOT:-./data/meeting}:/data
```

## 🔄 Migration Strategies

### PC1 Migration Approach

1. **Phase 1**: Extract Authentik to pc1-auth
   - Maintain external Redis/PostgreSQL connections
   - Update DNS routing for authentication endpoints

2. **Phase 2**: Move webtop services to pc1-web
   - Preserve webtop2 configuration volume
   - Update mcp-webtop mount paths

3. **Phase 3**: Consolidate DevOps tools in pc1-devops
   - Add mcp-quickchart for visualization
   - Maintain cross-stack communication

### PC2 Migration Approach

1. **Phase 1**: Separate core runtime services
   - Move node-runner, python-runner, redis to pc2-core
   - Preserve development environment configurations

2. **Phase 2**: Organize MCP tools in pc2-tools
   - Group mcp-docker, mcp-glama, mcp-devops
   - Maintain WSL Docker socket compatibility

3. **Phase 3**: Specialized services in pc2-devops
   - Keep Thai language services together
   - Preserve audio processing configurations

## 🛠️ Cross-Stack Communication

### PC1 Communication Patterns
```yaml
# Webtop management across stacks
environment:
  WEBTOPS_ROUTER_BASE_URL: http://webtop2.pc1-web-net:3000

# DevOps accessing core services
environment:
  DEV_HOST_BASE_URL: http://dev-host.pc1
```

### PC2 Communication Patterns
```yaml
# Tools accessing core services
environment:
  MCP_TASK_SERVERS: '[{"name":"mcp-devops","url":"http://mcp-devops.pc2-tools-net:8325"}]'

# Webtop router integration
environment:
  WEBTOPS_ROUTER_BASE_URL: http://webtops-router.pc2-web-net:3001
```

## 📋 Port Allocation Summary

### PC1 Port Ranges
| Stack | Service | Port | Purpose |
|-------|---------|------|---------|
| core | 1mcp-agent | 3051 | MCP aggregation |
| core | mcp-agents | 8046 | Agents API |
| core | mcp-rag | 8055 | RAG services |
| core | mcp-tester | 8335 | Testing |
| core | mcp-playwright | 8260 | Browser automation |
| auth | authentik-http | 9000 | Auth HTTP |
| auth | authentik-https | 9443 | Auth HTTPS |
| web | webtop2 | 3003 | Webtop UI |
| web | mcp-webtop | 8055 | Webtop management |
| devops | mcp-devops | 8325 | DevOps tools |
| devops | mcp-quickchart | 8270 | Chart generation |

### PC2 Port Ranges
| Stack | Service | Port | Purpose |
|-------|---------|------|---------|
| core | redis | 6379 | Cache |
| core | dev-proxy-admin | 2019 | Proxy admin |
| tools | mcp-docker | 8340 | Docker API |
| tools | mcp-glama | 7214 | AI gateway |
| tools | mcp-devops | 8325 | DevOps tools |
| web | webtops-router | 3001 | Session router |
| web | mcp-webtops | 8091 | Webtop management |
| web | webtops-cp | 3005 | Control panel |
| devops | mcp-tester | 8330 | Testing |
| devops | mcp-agents | 8046 | Agents API |
| devops | mcp-playwright | 8460 | Browser automation |
| devops | mcp-instrans | 7216 | Thai STT |
| devops | mcp-meeting | 7208 | Meeting transcription |
| devops | mcp-vaja | 7217 | Thai language |

## 🚀 Operational Considerations

### PC1-Specific Considerations
- **Authentication**: Authentik requires external database setup
- **Webtop Migration**: Preserve existing webtop2 configurations
- **DNS Updates**: Update routing for authentication endpoints

### PC2-Specific Considerations
- **Thai Language**: Ensure AI4Thai API keys are configured
- **Audio Storage**: Plan for meeting audio file management
- **WSL Compatibility**: Maintain Docker socket access patterns

### Shared Considerations
- **Network Creation**: Use create-networks.yml before startup
- **Environment Files**: Copy .env.example to .env for each stack
- **Dependency Order**: Start core → tools → web → devops

## 📚 Success Metrics

### PC1 Success Criteria
- ✅ Authentik services accessible via VPN
- ✅ Webtop2 sessions preserved and manageable
- ✅ DevOps tools can access core services
- ✅ Cross-stack communication functional

### PC2 Success Criteria
- ✅ Development environments accessible
- ✅ Thai language services functional
- ✅ Meeting transcription working
- ✅ Cross-platform development supported

---

*These patterns complement the general stack reorganization patterns and provide host-specific guidance for PC1 and PC2 migrations.*
