# LINE Webhook Deployment Guide

## Overview
This guide covers deploying the LINE webhook receiver service (`mcp-line`) in the idc1 stack.

## Prerequisites
- LINE Developers Console access
- idc1 server access
- Docker and docker-compose installed

## Service Architecture
```
LINE Platform → HTTPS → line.idc1.surf-thailand.com → Caddy → mcp-line:8088
```

## Configuration

### 1. LINE Console Setup
1. Go to [LINE Developers Console](https://developers.line.biz/console/)
2. Create/select provider and channel (Messaging API)
3. Note credentials:
   - Channel ID: `2008804355`
   - Channel Secret: `43af9b639dbe4693cd04faef7a62229e`
   - Channel Access Token: `IyiITYBIjU8h2mta2HOsrefKRuKVcZFcv37i6AQNCxTtWYBoRWJ9+bagTajkCBnGekeRMUCv75GqbXmDVk/cHaFTaMcXyI7qVpE2iAGGh1nLZaJ9uNGb8UEDmI5M97EmGbStHFxvIo5N5oeiOgCAQAdB04t89/1O/w1cDnyilFU=`

### 2. Webhook URL Configuration
Set in LINE Console:
- **Webhook URL**: `https://line.idc1.surf-thailand.com/webhook/line`
- Enable "Use webhook"

### 3. Environment Variables
Add to `stacks/idc1-stack/.env`:
```bash
LINE_CHANNEL_SECRET=43af9b639dbe4693cd04faef7a62229e
LINE_CHANNEL_ACCESS_TOKEN=IyiITYBIjU8h2mta2HOsrefKRuKVcZFcv37i6AQNCxTtWYBoRWJ9+bagTajkCBnGekeRMUCv75GqbXmDVk/cHaFTaMcXyI7qVpE2iAGGh1nLZaJ9uNGb8UEDmI5M97EmGbStHFxvIo5N5oeiOgCAQAdB04t89/1O/w1cDnyilFU=
MCP_LINE_PORT=8088
MCP_LINE_BUILD_CONTEXT=../mcp/mcp-line
```

## Deployment

### 1. Deploy Stack
```bash
cd stacks/idc1-stack
powershell -ExecutionPolicy Bypass -File ../../scripts/idc1-stack.ps1 -Action up -Profile mcp-suite
```

### 2. Verify Service
```bash
# Health check
curl https://line.idc1.surf-thailand.com/health

# Expected response
{"status":"ok","signatureConfigured":true,"accessTokenConfigured":true}
```

### 3. Test Webhook
```bash
# This should return 401 without LINE signature (expected)
curl -X POST https://line.idc1.surf-thailand.com/webhook/line \
  -H "Content-Type: application/json" \
  -d '{"events":[]}'

# Response: {"detail":"invalid_signature"}
```

## Service Endpoints

### Health Check
- **URL**: `/health`
- **Method**: GET
- **Response**: Service status and configuration

### Webhook Receiver
- **URL**: `/webhook/line`
- **Method**: POST
- **Headers**: `X-Line-Signature` (required)
- **Body**: LINE webhook event JSON
- **Response**: Processing status

## Security Features
- **Signature Verification**: Validates `X-Line-Signature` using `LINE_CHANNEL_SECRET`
- **Token Validation**: Checks `LINE_CHANNEL_ACCESS_TOKEN` availability
- **Request Logging**: Logs webhook events for debugging

## Troubleshooting

### Common Issues
1. **401 Invalid Signature**: Request missing or invalid `X-Line-Signature`
2. **Service Unavailable**: Docker container not running
3. **DNS Resolution**: `line.idc1.surf-thailand.com` not reachable

### Debug Commands
```bash
# Check container status
docker ps | grep mcp-line

# View logs
docker logs idc1-stack-mcp-line-1

# Test locally
docker run -p 8088:8088 mcp-line
```

## Local Development
```bash
# Build and test locally
cd mcp/mcp-line
docker build -t mcp-line .
docker run -p 8088:8088 \
  -e LINE_CHANNEL_SECRET=your_secret \
  -e LINE_CHANNEL_ACCESS_TOKEN=your_token \
  mcp-line
```

## Monitoring
- Health endpoint: `https://line.idc1.surf-thailand.com/health`
- Container logs: `docker logs idc1-stack-mcp-line-1`
- Caddy access logs: `/var/log/caddy/access.log` on idc1

## Files Modified
- `mcp/mcp-line/` - New webhook service
- `stacks/idc1-stack/docker-compose.yml` - Service definition
- `sites/idc1/config/Caddyfile` - Reverse proxy configuration
- `stacks/idc1-stack/.env.example` - Environment template

## Related Documentation
- [LINE Messaging API Documentation](https://developers.line.biz/en/docs/messaging-api/)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [Caddy Reverse Proxy](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy)
