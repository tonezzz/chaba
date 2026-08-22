# Yomi Port Conflict: Docker Container vs Systemd Service

## What it is

Port 3000 conflict between Docker container `yomi-api` and systemd service `yomi-api.service` causing repeated service failures and notification errors.

## Context/Background

The Yomi API server was transitioned from a host-based systemd service to a containerized deployment using Docker. However, the systemd service was not properly disabled, leading to both the Docker container and systemd service attempting to bind to port 3000 simultaneously.

## Key Details

### Root Cause
- **Docker Container**: `yomi-api` (node:20-alpine) running successfully on port 3000
- **Systemd Service**: `yomi-api.service` still enabled and attempting to start
- **Port Conflict**: Both trying to bind to 0.0.0.0:3000
- **Error Pattern**: `EADDRINUSE: address already in use 0.0.0.0:3000`
- **Impact**: 893+ failed restart attempts, continuous notification errors

### Container Configuration
- **Container Name**: `yomi-api`
- **Image**: node:20-alpine
- **Port Mapping**: 3000:3000 (host:container)
- **Health Check**: `/api/yomi/health` (10s interval, 5s timeout, 5 retries, 10s start period)
- **Status**: Healthy and active
- **Location**: `/home/tony/CascadeProjects/chaba/stacks/web/docker-compose.yml` (lines 326-373)

### Systemd Service State
- **Service**: `yomi-api.service`
- **Location**: `/etc/systemd/system/yomi-api.service`
- **Status**: Disabled (after fix)
- **Previous State**: Enabled with auto-restart, failing repeatedly
- **Restart Count**: 893+ failed attempts before fix

### Timer Service Dependencies
When switching from host-based to containerized deployment, timer services required dependency updates:

**Before (Host-based)**:
- `yomi-fetch.service`: `After=network.target yomi-api.service`
- `yomi-process.service`: `After=network.target yomi-api.service`

**After (Containerized)**:
- `yomi-fetch.service`: `After=network.target docker.service`, `Requires=docker.service`
- `yomi-process.service`: `After=network.target docker.service`, `Requires=docker.service`

### Service Override Preservation
The `yomi-process.service` had an override configuration at `/etc/systemd/system/yomi-process.service.d/override.conf` containing:
- Extended timeout (1800s)
- Gemini API configuration
- Gemini processing settings

This override was preserved during the dependency updates to maintain functionality.

## Technical Details

### Docker Compose Configuration
```yaml
yomi-api:
  container_name: yomi-api
  image: node:20-alpine
  restart: unless-stopped
  working_dir: /app/yomi
  command: sh -c "npm install && node yomi-api.mjs"
  ports:
    - "3000:3000"
  healthcheck:
    test: ["CMD", "node", "-e", "require('http').get('http://localhost:3000/api/yomi/health', (r) => {process.exit(r.statusCode === 200 ? 0 : 1)})"]
    interval: 10s
    timeout: 5s
    retries: 5
    start_period: 10s
```

### Systemd Service Configuration (Disabled)
```ini
[Unit]
Description=Yomi API Server - HTTP API for Yomi data
After=network.target postgres.service

[Service]
Type=simple
User=tony
WorkingDirectory=/home/tony/CascadeProjects/chaba/scripts/yomi
ExecStart=/usr/bin/node yomi-api.mjs
Environment=YOMI_API_PORT=3000
Environment=YOMI_API_HOST=0.0.0.0
Restart=always
RestartSec=10
```

### Updated Timer Service Configuration
```ini
[Unit]
Description=Yomi Fetch - Fetch conversations from LINE API
After=network.target docker.service
Requires=docker.service

[Service]
Type=oneshot
User=tony
WorkingDirectory=/home/tony/CascadeProjects/chaba/scripts/yomi
ExecStart=/usr/bin/node fetch-conversations.mjs
```

## Usage/Commands

### Check Port Usage
```bash
# Check what's using port 3000
ss -tlnp | grep :3000

# Check Docker containers
docker ps -a | grep yomi-api

# Check systemd service status
systemctl status yomi-api.service
```

### Disable Systemd Service (Container Active)
```bash
# Stop the systemd service
sudo systemctl stop yomi-api.service

# Disable from auto-start
sudo systemctl disable yomi-api.service

# Verify disabled status
systemctl status yomi-api.service
```

### Update Timer Dependencies
```bash
# Edit fetch service
sudo sed -i 's/After=network.target yomi-api.service/After=network.target docker.service/g' /etc/systemd/system/yomi-fetch.service
sudo sed -i '/After=network.target docker.service/a Requires=docker.service' /etc/systemd/system/yomi-fetch.service

# Edit process service
sudo sed -i 's/After=network.target yomi-api.service/After=network.target docker.service/g' /etc/systemd/system/yomi-process.service
sudo sed -i '/After=network.target docker.service/a Requires=docker.service' /etc/systemd/system/yomi-process.service

# Reload systemd
sudo systemctl daemon-reload

# Verify configuration
systemctl cat yomi-fetch.service
systemctl cat yomi-process.service
```

### Verify Container Health
```bash
# Check container status
docker ps | grep yomi-api

# Check container health
docker inspect yomi-api --format '{{.State.Health.Status}}'

# Test API endpoint
curl -s http://localhost:3000/api/yomi/health
```

### Revert to Host-based Service (If Needed)
```bash
# Stop Docker container
docker stop yomi-api
docker rm yomi-api

# Enable systemd service
sudo systemctl enable yomi-api.service
sudo systemctl start yomi-api.service

# Update timer dependencies back
sudo sed -i 's/After=network.target docker.service/After=network.target yomi-api.service/g' /etc/systemd/system/yomi-fetch.service
sudo sed -i 's/After=network.target docker.service/After=network.target yomi-api.service/g' /etc/systemd/system/yomi-process.service
sudo sed -i '/Requires=docker.service/d' /etc/systemd/system/yomi-fetch.service
sudo sed -i '/Requires=docker.service/d' /etc/systemd/system/yomi-process.service

# Reload systemd
sudo systemctl daemon-reload
```

## Troubleshooting

### Port Conflict Symptoms
**Symptoms**:
- Systemd service failing with `EADDRINUSE: address already in use 0.0.0.0:3000`
- Continuous notification errors about service failures
- High restart counts in systemd logs
- API still working (via Docker container)

**Diagnosis**:
```bash
# Check what's using port 3000
ss -tlnp | grep :3000

# Check Docker containers
docker ps | grep yomi-api

# Check systemd service logs
journalctl -u yomi-api.service -n 50
```

**Solution**: Disable systemd service if container is active, or stop container if using systemd service

### Timer Services Failing
**Symptoms**: Timer services failing to start after containerization

**Diagnosis**:
```bash
# Check timer status
systemctl status yomi-fetch.timer
systemctl status yomi-process.timer

# Check service dependencies
systemctl cat yomi-fetch.service
systemctl cat yomi-process.service
```

**Solution**: Update service dependencies from `yomi-api.service` to `docker.service`

### Override Configuration Lost
**Symptoms**: Service configuration changes lose custom settings

**Diagnosis**:
```bash
# Check for override files
ls -la /etc/systemd/system/yomi-process.service.d/

# View current configuration
systemctl cat yomi-process.service
```

**Solution**: Preserve override configurations in `.service.d/override.conf` files when updating base service files

## Prevention

### Deployment Documentation
- Document which deployment method is active (Docker vs systemd)
- Maintain clear migration procedures between deployment methods
- Document required dependency changes for timer services
- Track override configurations and their purposes

### Service Management
- When switching deployment methods, always disable the old method first
- Verify port availability before enabling services
- Check for existing containers/services on target ports
- Use `systemctl disable` rather than just stopping services

### Configuration Management
- Preserve override configurations during service updates
- Document the purpose of each override file
- Use version control for systemd service configurations
- Test timer dependency changes before production deployment

### Monitoring
- Monitor systemd service restart counts
- Alert on port conflict errors
- Track container health status
- Monitor timer service execution success rates

## Related Documentation

- [yomi.md](yomi.md) - Main Yomi documentation
- [yomi-media-analysis-http500.md](yomi-media-analysis-http500.md) - Systemd service configuration patterns
- Docker Compose configuration: `/home/tony/CascadeProjects/chaba/stacks/web/docker-compose.yml`

## Tags

yomi, docker, systemd, port-conflict, deployment, service-management, troubleshooting