# PC1 Web Stack

Dedicated stack for web services, user interfaces, and development hosting.

## Services

- **openchat-ui** - Chat interface UI
  - Port: 3170 → 3000
  - Purpose: Web-based chat interface for AI services

- **caddy** - Reverse proxy and web server
  - Ports: 3080 → 80, 3443 → 443
  - Purpose: HTTP/HTTPS ingress and routing

- **dev-host** - Development host environment
  - Port: 2223 → 22
  - Purpose: SSH access and development workspace

## Usage

```bash
# Start Web stack
docker-compose --file docker-compose.yml up -d

# Check service health
curl http://localhost:3170  # OpenChat UI
curl http://localhost:3080  # Caddy proxy
ssh -p 2223 localhost       # Dev-host SSH

# Access chat interface
open http://localhost:3170

# Access via Caddy proxy
open http://localhost:3080
```

## Cross-Host Access

The Web services are designed to be accessible from other hosts:

### From pc2-worker or other hosts
```json
// 1mcp.json configuration
{
  "mcpServers": {
    "pc1-openchat-ui": {
      "transport": "streamableHttp",
      "url": "http://pc1.vpn:3170/mcp",
      "tags": ["pc1", "openchat", "ui", "remote"],
      "enabled": true
    },
    "pc1-caddy": {
      "transport": "streamableHttp",
      "url": "http://pc1.vpn:3080/mcp",
      "tags": ["pc1", "caddy", "proxy", "remote"],
      "enabled": true
    },
    "pc1-dev-host": {
      "transport": "streamableHttp",
      "url": "http://pc1.vpn:2223/mcp",
      "tags": ["pc1", "dev-host", "remote"],
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
# OPENCHAT_OPENAI_API_HOST=http://pc1.vpn:8181
# CADDY_INGRESS_DOMAINS=yourdomain.com
# DEV_HOST_BASE_URL=http://pc1.vpn:3000
```

## Network

- **Network**: `pc1-web-net` (172.25.0.0/16)
- **VPN Access**: Available via `pc1.vpn` endpoints
- **Ingress**: Caddy provides HTTP/HTTPS entry point

## Features

### Chat Interface (OpenChat UI)
- **Modern UI**: React-based chat interface
- **AI Integration**: Connects to AI stack services
- **Real-time**: WebSocket-based communication
- **Responsive**: Mobile-friendly design

### Reverse Proxy (Caddy)
- **HTTPS**: Automatic SSL certificate management
- **Routing**: Service discovery and load balancing
- **Security**: Request filtering and rate limiting
- **Logging**: Access logs and monitoring

### Development Host
- **SSH Access**: Secure remote development
- **Workspace**: Full repository access
- **Docker Integration**: Container management
- **Preview**: Development server hosting

## Requirements

- Network access to AI stack for chat functionality
- Sufficient memory for web applications
- SSL certificates for production HTTPS
- SSH keys for development host access

## Data Persistence

- **caddy-config**: Caddy configuration and certificates
- **caddy-data**: SSL certificates and logs

## Security Considerations

- **HTTPS**: Use SSL certificates in production
- **SSH Keys**: Secure key management for dev-host
- **Network Access**: Consider VPN-only access
- **Rate Limiting**: Configure Caddy for abuse prevention

## Integration

This stack integrates with:
- **pc1-ai** - AI services for chat functionality
- **pc1-core** - Core MCP services
- **pc2-worker** - Remote development access
- **External services** - Via Caddy ingress

## Caddy Configuration

The Caddyfile provides:
- **HTTP → HTTPS** redirects
- **Service routing** to internal containers
- **Health checks** and monitoring
- **Static file serving** for web assets

## Development Workflow

### Local Development
```bash
# Access chat interface
open http://localhost:3170

# SSH into development host
ssh -p 2223 user@localhost

# Access via proxy
open http://localhost:3080/chat
```

### Remote Access
```bash
# From VPN client
open http://pc1.vpn:3170
ssh -p 2223 user@pc1.vpn
open https://yourdomain.com
```

## Service Dependencies

- **OpenChat UI** depends on **pc1-ai** stack for AI services
- **Caddy** provides ingress for all web services
- **Dev-host** provides development environment
- **All services** accessible via VPN endpoints

## Monitoring

- **Health Checks**: All services expose `/health` endpoints
- **Logs**: Centralized logging via Docker
- **Metrics**: Caddy provides access statistics
- **Alerts**: Configure health monitoring
