# Token Optimization Runbook

## Overview

This runbook provides operational procedures for managing the token optimization infrastructure implemented across the development environment.

## Infrastructure Components

### 1. MCP Filtering (mcp-filter)
- **Location**: `/tmp/mcp-filter-venv/`
- **Version**: 0.2.0
- **Purpose**: Filter MCP server tools to reduce token overhead
- **Filtered Servers**: Yomi, PostgreSQL, GitHub

### 2. Headroom Proxy
- **Location**: `/tmp/headroom-venv/`
- **Version**: 0.34.0
- **Purpose**: Compress data before it reaches the LLM
- **Default Port**: 8787
- **Mode**: cache (provider prefix cache stability)

### 3. Configuration Files
- **MCP Config**: `~/.config/devin/mcp_config.json`
- **Filter Scripts**: `.windsurf/run-*-filtered-mcp.sh`
- **Proxy Script**: `.windsurf/start-headroom-proxy.sh`

## Operational Procedures

### Starting Headroom Proxy

**Manual Start**:
```bash
/home/tony/CascadeProjects/chaba/.windsurf/start-headroom-proxy.sh
```

**Background Start**:
```bash
nohup /home/tony/CascadeProjects/chaba/.windsurf/start-headroom-proxy.sh > /tmp/headroom.log 2>&1 &
```

**Verify Proxy Running**:
```bash
curl http://127.0.0.1:8787/health
```

**Stop Proxy**:
```bash
pkill -f "headroom proxy"
```

### Managing MCP Filtering

**Check Filter Status**:
```bash
# List available tools for filtered servers
# Use Devin's mcp_list_tools function for each server
```

**Modify Filter Configuration**:
1. Edit the appropriate filter script in `.windsurf/`
2. Modify `MF_ALLOW_TOOLS` environment variable
3. Restart Devin Desktop to apply changes

**Add Tool to Allowlist**:
```bash
# Example: Add 'send_message' to Yomi filter
export MF_ALLOW_TOOLS="list_conversations,get_chat_messages,get_insight,send_message"
```

**Disable Filtering for a Server**:
1. Edit `~/.config/devin/mcp_config.json`
2. Revert to original server configuration
3. Restart Devin Desktop

### Managing Disabled MCP Servers

**Enable Disabled Server**:
1. Edit `~/.config/devin/mcp_config.json`
2. Remove `"disabled": true` from server configuration
3. Restart Devin Desktop

**Disable Active Server**:
1. Edit `~/.config/devin/mcp_config.json`
2. Add `"disabled": true` to server configuration
3. Restart Devin Desktop

## Monitoring and Maintenance

### Token Usage Monitoring

**Check Token Usage**:
- Monitor Devin Desktop quota usage
- Review session token consumption
- Track MCP tool usage patterns

**Expected Token Reduction**:
- MCP filtering: 65-70% reduction in MCP overhead
- Headroom proxy: 30-50% reduction in data operations
- Overall expected: 60-80% token reduction

### Performance Monitoring

**Check Proxy Latency**:
```bash
# Measure proxy response time
time curl http://127.0.0.1:8787/health
```

**Monitor MCP Server Performance**:
- Track tool execution time
- Monitor for proxy-related delays
- Check for error rates

### Log Management

**Headroom Proxy Logs**:
```bash
# View proxy logs if running in foreground
# Check /tmp/headroom.log if running in background
tail -f /tmp/headroom.log
```

**MCP Filter Logs**:
```bash
# Token estimates are enabled via MF_SHOW_TOKEN_ESTIMATES=1
# Check Devin logs for token estimate output
```

## Troubleshooting

### Common Issues

**Issue**: MCP server not accessible after filtering
**Solution**:
1. Check filter script syntax
2. Verify tool names in allowlist are correct
3. Check MCP server is running
4. Review Devin logs for errors

**Issue**: Headroom proxy not starting
**Solution**:
1. Check port 8787 is not in use: `lsof -i :8787`
2. Verify Python virtual environment is intact
3. Check proxy script permissions
4. Review proxy logs for errors

**Issue**: No token reduction observed
**Solution**:
1. Verify filtering is active (check tool counts)
2. Ensure Headroom proxy is being used
3. Check token measurement methodology
4. Review configuration for errors

**Issue**: Errors after MCP configuration changes
**Solution**:
1. Verify JSON syntax in mcp_config.json
2. Check filter scripts are executable
3. Restart Devin Desktop
4. Rollback changes if needed

### Emergency Procedures

**Complete Rollback**:
1. Stop Headroom proxy
2. Restore original mcp_config.json from backup
3. Restart Devin Desktop
4. Verify all services function normally

**Backup Configuration Files**:
```bash
# Backup MCP configuration
cp ~/.config/devin/mcp_config.json ~/.config/devin/mcp_config.json.backup

# Backup filter scripts
cp .windsurf/run-*-filtered-mcp.sh .windsurf/backup/
```

## Maintenance Tasks

### Weekly Maintenance
- Review token usage statistics
- Check for MCP server updates
- Monitor proxy performance
- Review error logs

### Monthly Maintenance
- Update mcp-filter to latest version
- Update Headroom proxy to latest version
- Review and optimize filter configurations
- Audit disabled servers for potential re-enablement

### Quarterly Review
- Evaluate overall token optimization effectiveness
- Consider additional optimization opportunities
- Review cost savings achieved
- Plan future improvements

## Configuration Reference

### MCP Filter Environment Variables

**MF_ALLOW_TOOLS**: Comma-separated list of allowed tool names
**MF_SHOW_TOKEN_ESTIMATES**: Enable token estimate logging (1 = enabled)
**MF_TRANSPORT**: Transport type (stdio or http)
**MF_STDIO_COMMAND**: Upstream MCP server command
**MF_STDIO_ARGS**: Arguments for upstream MCP server

### Headroom Proxy Configuration

**--host**: Host to bind to (default: 127.0.0.1)
**--port**: Port to bind to (default: 8787)
**--mode**: Optimization mode (token or cache)
**--no-optimize**: Disable optimization (passthrough mode)
**--no-cache**: Disable semantic caching
**--telemetry**: Enable anonymous usage telemetry

## Security Considerations

### Access Control
- Headroom proxy binds to localhost only
- MCP filtering uses local proxy layer
- No external network exposure

### Data Privacy
- Headroom proxy processes data locally
- No data sent to external services
- Token estimates logged locally only

### Updates
- Review security updates for mcp-filter
- Review security updates for Headroom
- Test updates in non-production environment first

## Support and Documentation

**SSOT Documentation**: `ssot.token-optimization.yml`
**Implementation Plan**: `token-optimization-implementation-plan.md`
**Testing Guide**: `token-optimization-testing.md`
**MCP Server Audit**: `mcp-server-audit.md`

## Contact and Escalation

**For issues with**:
- MCP filtering: Review mcp-filter documentation
- Headroom proxy: Review Headroom documentation
- Devin configuration: Review Devin Desktop documentation

**Emergency Contact**: System administrator

## Change History

| Date | Change | Author |
|------|--------|--------|
| 2026-08-05 | Initial implementation | tony |
| | | |
| | | |
