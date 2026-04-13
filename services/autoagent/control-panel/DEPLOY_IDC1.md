# Deploy Skill Creator to idc1.surf-thailand.com

## Overview

Deploy the Skill Creator UI to be accessible via `https://assistance.idc1.surf-thailand.com/skills`

## Prerequisites

- SSH access to idc1 host
- sudo privileges for Caddy reload
- Skill Creator code deployed at `/home/chaba/chaba/services/autoagent/control-panel/`

## Method 1: Automated Deployment Script

### Step 1: Copy and run deployment script on idc1

```bash
# On your local machine, copy the script to idc1
scp /home/chaba/chaba/services/autoagent/control-panel/deploy-to-idc1.sh chaba@idc1.surf-thailand.com:/tmp/

# SSH to idc1
ssh chaba@idc1.surf-thailand.com

# Run the deployment script
cd /tmp
chmod +x deploy-to-idc1.sh
sudo ./deploy-to-idc1.sh
```

## Method 2: Manual Deployment

### Step 1: Start Skill Creator Server

```bash
# SSH to idc1
ssh chaba@idc1.surf-thailand.com

# Navigate to control-panel
cd /home/chaba/chaba/services/autoagent/control-panel

# Install dependencies if needed
/home/chaba/chaba/.venv/bin/pip install aiohttp -q

# Start the server on port 8090
export WIKI_API_URL=http://localhost:3008
nohup /home/chaba/chaba/.venv/bin/python control-server.py --port 8090 > /tmp/skill-creator.log 2>&1 &

# Verify it's running
curl http://localhost:8090/skills | head -10
```

### Step 2: Update Caddyfile

```bash
# SSH to idc1 as root or use sudo
ssh chaba@idc1.surf-thailand.com

# Backup Caddyfile
sudo cp /etc/caddy/Caddyfile /etc/caddy/Caddyfile.backup.$(date +%Y%m%d)

# Edit Caddyfile
sudo nano /etc/caddy/Caddyfile
```

Add the following inside the `assistance.idc1.surf-thailand.com` site block:

```caddy
# Skill Creator UI
handle_path /skills/* {
    reverse_proxy 127.0.0.1:8090
}

handle /skills {
    redir /skills/ 308
}

# Skill Creator API
handle_path /api/skills/* {
    reverse_proxy 127.0.0.1:8090
}
```

### Step 3: Validate and Reload Caddy

```bash
# Validate Caddyfile
sudo caddy validate --config /etc/caddy/Caddyfile

# Reload Caddy
sudo systemctl reload caddy

# Check status
sudo systemctl status caddy
```

### Step 4: Test

```bash
# Test from idc1
curl -s https://assistance.idc1.surf-thailand.com/skills | head -20

# Test from local machine (after SSH tunnel if needed)
curl -s https://assistance.idc1.surf-thailand.com/api/skills/interpret \
  -X POST \
  -H "Content-Type: application/json" \
  -d '{"input": "check weather"}'
```

## Complete Caddyfile Example

Your `/etc/caddy/Caddyfile` should look something like this:

```caddy
# Global options
{
    auto_https off
}

# Assistance site
assistance.idc1.surf-thailand.com {
    # Jarvis WebSocket
    handle_path /jarvis/ws/* {
        strip_prefix /jarvis
        reverse_proxy 127.0.0.1:18018
    }
    
    # Jarvis API
    handle_path /jarvis/api/* {
        reverse_proxy 127.0.0.1:18018
    }
    
    # Jarvis Frontend
    handle_path /jarvis/* {
        reverse_proxy 127.0.0.1:18080
    }
    
    # Skill Creator UI (NEW)
    handle_path /skills/* {
        reverse_proxy 127.0.0.1:8090
    }
    
    handle /skills {
        redir /skills/ 308
    }
    
    # Skill Creator API (NEW)
    handle_path /api/skills/* {
        reverse_proxy 127.0.0.1:8090
    }
    
    # Default - frontend root
    handle {
        reverse_proxy 127.0.0.1:18080
    }
}

# Other sites...
```

## Verification

### Check Server is Running

```bash
# Check process
ps aux | grep control-server

# Check port
lsof -i :8090

# Check logs
tail -f /tmp/skill-creator.log
```

### Check Caddy Routing

```bash
# Test from idc1
curl -v http://localhost:8090/skills 2>&1 | head -30

# Test through Caddy
curl -v https://assistance.idc1.surf-thailand.com/skills 2>&1 | head -30
```

### Test API Endpoints

```bash
# Test interpret endpoint
curl -X POST \
  https://assistance.idc1.surf-thailand.com/api/skills/interpret \
  -H "Content-Type: application/json" \
  -d '{"input": "check the weather"}'

# Test Thai language
curl -X POST \
  https://assistance.idc1.surf-thailand.com/api/skills/interpret \
  -H "Content-Type: application/json" \
  -d '{"input": "ตรวจสอบสภาพอากาศ"}'
```

## Troubleshooting

### Server Won't Start

```bash
# Check Python dependencies
/home/chaba/chaba/.venv/bin/pip list | grep aiohttp

# Check port conflict
lsof -i :8090
kill -9 $(lsof -t -i:8090) 2>/dev/null

# Check logs
cat /tmp/skill-creator.log
```

### Caddy Errors

```bash
# Validate config
sudo caddy validate --config /etc/caddy/Caddyfile

# Check Caddy logs
sudo journalctl -u caddy -n 100 --no-pager

# Test config syntax
sudo caddy adapt --config /etc/caddy/Caddyfile
```

### 404 Errors

```bash
# Check handle_path vs handle
# Ensure path matching is correct

# Test locally on idc1
curl http://localhost:8090/
curl http://localhost:8090/skills
```

## Security Considerations

1. **Port Binding**: Skill Creator binds to `127.0.0.1:8090` (localhost only)
2. **TLS**: Terminated by Caddy (automatic HTTPS)
3. **Authentication**: Consider adding auth if needed

## Maintenance

### Auto-start on Boot

Create systemd service at `/etc/systemd/system/skill-creator.service`:

```ini
[Unit]
Description=Skill Creator UI
After=network.target

[Service]
Type=simple
User=chaba
WorkingDirectory=/home/chaba/chaba/services/autoagent/control-panel
Environment=WIKI_API_URL=http://localhost:3008
ExecStart=/home/chaba/chaba/.venv/bin/python control-server.py --port 8090
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable:
```bash
sudo systemctl daemon-reload
sudo systemctl enable skill-creator
sudo systemctl start skill-creator
```

## URLs After Deployment

| Service | URL |
|---------|-----|
| Skill Creator UI | `https://assistance.idc1.surf-thailand.com/skills` |
| Skill Creator API | `https://assistance.idc1.surf-thailand.com/api/skills/*` |
| Jarvis Frontend | `https://assistance.idc1.surf-thailand.com/jarvis/` |
| Jarvis API | `https://assistance.idc1.surf-thailand.com/jarvis/api/*` |
