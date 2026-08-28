---
category: operations
---

# Key Troubleshooting

### Headroom Proxy Issues
**Proxy Not Running**:
```bash
curl http://127.0.0.1:8787/health
.windsurf/start-headroom-proxy.sh
```

**No Compression Occurring**:
- Check if Devin is configured to use proxy
- Verify ANTHROPIC_BASE_URL is set correctly
- Check proxy stats for request count

**High Latency**:
- Check system resources (CPU, memory)
- Review proxy configuration
- Check network connectivity

### MCP Filtering Issues
**Missing Tools**:
- Review filter script configuration
- Check tool names in allowlist
- Verify MCP server is running
- Restart Devin Desktop

**Server Health Issues**:
- Check upstream server status
- Review filter script logs
- Verify command paths are correct

### Emergency Rollback
```bash
# Complete rollback
# 1. Stop Headroom proxy
# 2. Restore original mcp_config.json from backup
# 3. Restart Devin Desktop
# 4. Verify all services function normally
```

