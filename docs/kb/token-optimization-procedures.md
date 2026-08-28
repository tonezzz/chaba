---
category: operations
---

# Operational Procedures

### Starting Headroom Proxy
```bash
# Manual start
.windsurf/start-headroom-proxy.sh

# Verify running
curl http://127.0.0.1:8787/health

# Stop proxy
pkill -f "headroom proxy"
```

### Managing MCP Filtering
```bash
# Modify filter configuration
# Edit appropriate filter script in .windsurf/
# Modify MF_ALLOW_TOOLS environment variable
# Restart Devin Desktop to apply changes

# Disable filtering for a server
# Edit ~/.config/devin/mcp_config.json
# Revert to original server configuration
# Restart Devin Desktop
```

# Enable disabled server
# Edit ~/.config/devin/mcp_config.json
# Remove "disabled": true from server configuration
# Restart Devin Desktop
```

