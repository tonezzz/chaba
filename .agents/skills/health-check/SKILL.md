---
name: health-check
description: Check health of all services defined in ssot.health.yml with auto network detection (DEPRECATED - use MCP health server tools)
allowed-tools:
  - read
  - exec
  - grep
triggers:
  - user
  - model
---

**DEPRECATED**: This skill is deprecated in favor of the MCP health server tools. Please use the MCP health server tools directly:
- `mcp-health:check_health` - Run health checks for all services
- `mcp-health:get_health_status` - Get current health status
- `mcp-health:get_health_history` - Get historical health data
- `mcp-health:get_health_summary` - Get health summary and trends
- `mcp-health:analyze_dependencies` - Analyze service dependencies
- `mcp-health:get_alerts` - Get active and historical alerts
- `mcp-health:acknowledge_alert` - Acknowledge alerts
- `mcp-health:get_alert_config` - Get alert configuration
- `mcp-health:check_port_conflicts` - Check for port conflicts
- `mcp-health:validate_proxy_config` - Validate Caddy proxy configuration
- `mcp-health:restart_service` - Safely restart services
- `mcp-health:get_troubleshooting_info` - Get enhanced troubleshooting information

**Migration Guide**:
1. Replace skill invocation with `mcp-health:check_health` tool call
2. Use `mcp-health:get_troubleshooting_info` for recovery guidance
3. Use `mcp-health:analyze_dependencies` for dependency analysis
4. Use `mcp-health:get_alerts` for alert management

**Legacy Implementation** (for backward compatibility):

This skill now acts as a convenience wrapper for the MCP health server. The MCP server provides:
- Enhanced capabilities (historical tracking, alerts, advanced monitoring)
- Better performance (database persistence, optimized queries)
- Standardized interface (MCP protocol integration)
- Advanced features (port conflict detection, proxy validation, automated recovery)

The MCP health server is the authoritative source for health monitoring. This skill is maintained for backward compatibility and will be removed in a future update.

**Direct MCP Tool Usage Example**:
Instead of invoking this skill, use:
```
Call tool: mcp-health:check_health
Parameters: {} (for all services) or {"service": "Caddy"} (for specific service)
```

**Benefits of MCP Health Server**:
- Historical tracking and trend analysis
- Alert system with notifications
- Port conflict detection
- Proxy configuration validation
- Enhanced dependency analysis
- Automated service recovery
- Enhanced troubleshooting guidance with SSOT recovery actions
