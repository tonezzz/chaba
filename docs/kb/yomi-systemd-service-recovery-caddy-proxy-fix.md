# Yomi Systemd Service Recovery and Caddy Proxy Fix

## What it is

Yomi API service failure due to systemd service being stopped (port conflict) and Caddy proxy using incorrect routing directive, causing external API access failures.

## Context/Background

The Yomi API systemd service was found to be inactive while the Docker container was also not running. This caused external API access failures through the Caddy proxy. The issue was diagnosed using mcp-health monitoring and resolved by restarting the systemd service and correcting the Caddy proxy configuration.

## Key Details

### Root Cause Analysis
- **Systemd Service Status**: `yomi-api.service` was inactive (dead)
- **Port Conflict**: Previous EADDRINUSE error on port 3000 caused service to stop
- **Docker Container Status**: Container `yomi-api` was not running (Created state)
- **Caddy Proxy Issue**: Using `handle` instead of `handle_path` for Yomi API routes
- **External Access**: Failed with 404 errors via Caddy proxy on port 8080

### Service Recovery Process
1. **Diagnosed with mcp-health**: Identified Yomi API services as error state
2. **Checked systemd status**: Found service inactive with EADDRINUSE error in logs
3. **Killed conflicting processes**: Resolved port conflict on port 3000
4. **Restarted systemd service**: `systemctl enable yomi-api.service && systemctl start yomi-api.service`
5. **Verified direct access**: `curl http://localhost:3000/api/yomi/health` returned `{"ok":true}`
6. **Fixed Caddy proxy**: Changed from `handle_path` back to `handle` for `/api/yomi/*` routes
7. **Restarted web container**: Applied Caddyfile changes
8. **Verified external access**: `curl http://tony-omen.local:8080/api/yomi/health` returned `{"ok":true}`

### Caddy Proxy Configuration Correction
**Incorrect Configuration** (from SSOT troubleshooting steps):
```caddy
handle_path /api/yomi/* {
    reverse_proxy host.docker.internal:3000 {
        header_up Host localhost
    }
}
```

**Correct Configuration**:
```caddy
handle /api/yomi/* {
    reverse_proxy host.docker.internal:3000 {
        header_up Host localhost
    }
}
```

**Reason**: The Yomi API expects the full path `/api/yomi/*` to be preserved, not stripped. Using `handle_path` strips the prefix and forwards only `/health` to the backend, but the backend expects `/api/yomi/health`.

### Service State After Fix
- **Systemd Service**: Active and running (PID 2149433)
- **Direct API Access**: Working on port 3000
- **Caddy Proxy**: Working correctly with `handle` directive
- **External Access**: Working via `http://tony-omen.local:8080/api/yomi/*`
- **Health Check**: All Yomi API endpoints responding correctly

## Technical Details

### Systemd Service Configuration
```ini
[Unit]
Description=Yomi API Server - HTTP API for Yomi data
After=network.target postgres.service

[Service]
Type=simple
User=tony
WorkingDirectory=/home/tony/CascadeProjects/chaba/scripts/yomi
ExecStart=/usr/bin/node yomi-api.mjs
Environment=LLAMA_URL=http://localhost:8001/v1/chat/completions
Environment=YOMI_API_PORT=3000
Environment=YOMI_API_HOST=0.0.0.0
Environment=GEMINI_VISION_MODEL_PRIMARY=gemma-4-31b-it
Environment=GEMINI_VISION_MODEL_FALLBACK=gemma-4-26b-a4b-it
Environment=CONTEXT_MESSAGES_BEFORE=3
Environment=CONTEXT_MESSAGES_AFTER=3
Environment=POSTGRES_USER=chaba
Environment=POSTGRES_PASSWORD=chabapass
Environment=POSTGRES_DB=chaba
Environment=POSTGRES_HOST=127.0.0.1
Environment=POSTGRES_PORT=5432
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

### Service Override Configuration
```ini
[Service]
Environment=GEMINI_API_KEY=AQ.Ab8RN6IdyXzbZT6Inpiaf5yQG_RrVrKey7G07gYbQW6ghNUxvQ
```

### Yomi API Endpoint Structure
The Yomi API expects full path preservation:
- `/api/yomi/health` - Health check endpoint
- `/api/yomi/conversations` - List conversations
- `/api/yomi/messages?chat=<id>` - Get messages
- `/api/yomi/summarization-status` - Summarization statistics
- `/api/yomi/activity-status` - System activity status

## Usage/Commands

### Diagnose Yomi Service Issues
```bash
# Check systemd service status
systemctl status yomi-api.service

# Check service logs for errors
journalctl -u yomi-api.service -n 50

# Check port usage
ss -tlnp | grep :3000

# Test direct API access
curl -s http://localhost:3000/api/yomi/health

# Test external access via Caddy
curl -s http://tony-omen.local:8080/api/yomi/health
```

### Restart Yomi Systemd Service
```bash
# Kill conflicting processes on port 3000
pkill -f "node.*yomi-api"

# Enable and start service
systemctl enable yomi-api.service
systemctl start yomi-api.service

# Verify service status
systemctl status yomi-api.service
```

### Fix Caddy Proxy Configuration
```bash
# Edit Caddyfile
nano /home/tony/CascadeProjects/chaba/stacks/web/Caddyfile

# Change handle_path to handle for /api/yomi/* routes
# Restart web container
docker restart web

# Verify proxy works
curl -s http://tony-omen.local:8080/api/yomi/health
```

### Test Yomi API Endpoints
```bash
# Health check
curl -s http://localhost:3000/api/yomi/health

# Conversations list
curl -s http://localhost:3000/api/yomi/conversations

# Summarization status
curl -s http://localhost:3000/api/yomi/summarization-status

# Activity status
curl -s http://localhost:3000/api/yomi/activity-status
```

## Troubleshooting

### Service Not Starting
**Symptoms**: Systemd service fails to start or immediately stops

**Diagnosis**:
```bash
# Check service status
systemctl status yomi-api.service

# Check for port conflicts
ss -tlnp | grep :3000

# Check service logs
journalctl -u yomi-api.service -n 50 --no-pager
```

**Solution**: Kill conflicting processes, then restart service

### External Access Failing
**Symptoms**: Direct API works but external access via Caddy fails with 404

**Diagnosis**:
```bash
# Test direct access
curl -s http://localhost:3000/api/yomi/health

# Test external access
curl -s http://tony-omen.local:8080/api/yomi/health

# Check Caddyfile configuration
docker exec web cat /etc/caddy/Caddyfile | grep -A 5 "api/yomi"
```

**Solution**: Ensure Caddy uses `handle` not `handle_path` for Yomi API routes

### Port Conflict Errors
**Symptoms**: EADDRINUSE errors in service logs

**Diagnosis**:
```bash
# Check what's using port 3000
ss -tlnp | grep :3000

# Check for conflicting node processes
ps aux | grep node
```

**Solution**: Kill conflicting processes before starting service

## Prevention

### Service Management
- Always check for port conflicts before starting services
- Use `systemctl enable` for auto-start on boot
- Monitor service restart counts in logs
- Keep systemd service configurations in version control

### Caddy Proxy Configuration
- Use `handle` when backend expects full path preservation
- Use `handle_path` when backend expects prefix stripping
- Test proxy changes with both direct and external access
- Document the correct directive for each service

### Monitoring
- Use mcp-health for comprehensive service monitoring
- Set up alerts for service failures
- Monitor both systemd and container states
- Test external access regularly

### Documentation Updates
- Correct SSOT troubleshooting steps when errors are found
- Document the actual fix vs documented suggestions
- Keep KB entries updated with real-world solutions
- Maintain consistency between documentation and actual configuration

## Related Documentation

- **SSOT Health Configuration**: `/home/tony/CascadeProjects/chaba/docs/ssot/infrastructure/ssot.health.yml`
- **MCP Health Server**: Phase 3 enhancements for better service monitoring
- **Yomi Architecture**: `/home/tony/CascadeProjects/chaba-yomi/docs/architecture/yomi-architecture-separation.md`
- **Previous Port Conflict Issue**: `/home/tony/CascadeProjects/chaba-yomi/docs/kb/yomi-port-conflict-docker-systemd.md`

## Tags

yomi, systemd, service-recovery, caddy, proxy, troubleshooting, port-conflict, api-endpoints