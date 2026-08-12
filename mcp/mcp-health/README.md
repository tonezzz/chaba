# MCP Health Server

Centralized health monitoring and telemetry orchestrator for Chaba infrastructure. This MCP server provides standardized health check capabilities with historical tracking and analysis.

## Features

- **Centralized Health Monitoring**: Single interface for checking all services defined in SSOT health configuration
- **Network Profile Auto-Detection**: Automatically detects home vs mobile network profiles
- **Historical Tracking**: SQLite database stores health check history for trend analysis
- **Standardized Interface**: MCP protocol integration for seamless tool access
- **Health Summaries**: Uptime percentages, failure counts, and response time metrics

## Architecture

The MCP Health Server follows a hybrid orchestrator model:
- **MCP Layer**: Provides standardized tools and interfaces
- **Execution Layer**: Calls existing health-check skill for actual health checks
- **Persistence Layer**: SQLite database for historical data
- **Configuration Layer**: Reads from SSOT health configuration files

## Installation

The server is installed at `/home/tony/CascadeProjects/chaba/mcp/mcp-health/`

```bash
cd /home/tony/CascadeProjects/chaba/mcp/mcp-health
npm install
```

## Configuration

The server is configured in `/home/tony/.config/devin/mcp_config.json`:

```json
{
  "mcp-health": {
    "args": ["/home/tony/CascadeProjects/chaba/mcp/mcp-health/server.js"],
    "command": "/usr/bin/node",
    "env": {
      "HEALTH_CONFIG": "/home/tony/CascadeProjects/chaba/docs/ssot/infrastructure/ssot.health.yml",
      "HEALTH_SKILL": "/home/tony/CascadeProjects/chaba/.agents/skills/health-check/SKILL.md"
    }
  }
}
```

## Available Tools

### `check_health`
Run health checks for all services defined in SSOT health configuration.

**Parameters:**
- `service` (optional): Specific service name to check (checks all if not provided)

**Returns:**
```json
{
  "summary": {
    "total": 26,
    "healthy": 5,
    "degraded": 0,
    "error": 13,
    "unknown": 8,
    "profile": "home",
    "base_url": "http://tony-omen.local:8080"
  },
  "services_by_category": {
    "web": [...],
    "api": [...],
    "datastore": [...]
  },
  "all_services": [...],
  "recovery_suggestions": {...}
}
```

### `get_health_status`
Get current health status of all services from the database.

**Returns:**
```json
[
  {
    "service": "Caddy",
    "status": "healthy",
    "last_checked": "2026-08-12 03:47:35",
    "response_time": 40
  }
]
```

### `get_health_history`
Get historical health check data for analysis.

**Parameters:**
- `service_name` (optional): Service name to filter history
- `limit` (optional): Maximum number of records (default: 100)

**Returns:**
```json
[
  {
    "id": 1,
    "service_name": "Caddy",
    "status": "healthy",
    "response_time": 40,
    "error": null,
    "timestamp": "2026-08-12 03:47:35"
  }
]
```

### `get_health_summary`
Get health summary including uptime, failure counts, and trends.

**Parameters:**
- `service_name` (optional): Service name for specific summary

**Returns:**
```json
{
  "by_category": {
    "web": [...],
    "api": [...]
  },
  "all_services": [...]
}
```

### `analyze_dependencies`
Analyze service dependencies and detect cascading failures.

**Parameters:**
- `service_name` (optional): Service name to analyze dependencies for

**Returns:**
```json
{
  "dependency_analysis": {
    "yomi-api": {
      "current_status": "healthy",
      "dependencies": [...],
      "failing_dependencies": [...],
      "potential_cascading_failure": false,
      "dependency_failure_cause": null
    }
  },
  "total_services": 26,
  "services_with_dependencies": 4
}
```

### `get_alerts`
Get active and historical alerts.

**Parameters:**
- `service_name` (optional): Service name to filter alerts
- `severity` (optional): Severity level to filter (critical, error, degraded, info)
- `resolved` (optional): Filter for resolved vs unresolved alerts
- `limit` (optional): Maximum number of alerts to return (default: 50)

**Returns:**
```json
{
  "alerts": [
    {
      "id": 1,
      "service_name": "Yomi API",
      "alert_type": "service_failure",
      "severity": "critical",
      "message": "Service Yomi API is in error state",
      "acknowledged": false,
      "acknowledged_at": null,
      "resolved": false,
      "resolved_at": null,
      "created_at": "2026-08-12 06:00:00"
    }
  ],
  "total": 1,
  "alert_config": {...}
}
```

### `acknowledge_alert`
Acknowledge an alert to prevent duplicate notifications.

**Parameters:**
- `alert_id` (required): Alert ID to acknowledge

**Returns:**
```json
{
  "success": true,
  "message": "Alert 1 acknowledged",
  "alert_id": 1
}
```

### `get_alert_config`
Get current alert configuration from SSOT.

**Returns:**
```json
{
  "alert_config": {
    "enabled": true,
    "channels": [...],
    "thresholds": {...},
    "service_criticality": {...}
  },
  "service_criticality": {...},
  "thresholds": {...},
  "channels": [...]
}
```

## Alert Configuration

Alerts are configured in the SSOT health configuration file under the `alerts` section:

```yaml
alerts:
  enabled: true
  channels:
    - type: log
      enabled: true
      severity: [critical, error, degraded]
      description: Log alerts to system journal
    - type: webhook
      enabled: false
      url: "https://monitoring.example.com/webhook"
      severity: [critical]
      description: Webhook for external monitoring systems
  
  thresholds:
    critical_services_down: 3
    sustained_failure_minutes: 5
    recovery_notification: true
    response_time_threshold_ms: 5000
  
  service_criticality:
    critical: [caddy, postgres, gpu-queue]
    important: [yomi-api, status-api, trade-api, mddb-api]
    optional: [redis, weaviate, activepieces, frigate, camera-control, imagen2, txt2vid, thai-legal]
```

### Alert Types

- **service_failure**: Generated when a service transitions to error state
- **service_recovery**: Generated when a service recovers from error to healthy
- **performance_degradation**: Generated when response times exceed thresholds

### Severity Levels

- **critical**: Service failures for critical infrastructure
- **error**: Service failures for important services
- **degraded**: Performance issues or non-critical failures
- **info**: Recovery notifications and informational alerts

### Alert Channels

- **log**: Writes alerts to system journal via `logger` command
- **webhook**: Sends alerts to external monitoring systems (future enhancement)

## Network Profile Detection

The server automatically detects the network profile:

1. **Home Profile**: If `tony-omen.local` resolves, uses home network configuration
2. **Mobile Profile**: If home network unavailable, detects current IP and uses mobile configuration
3. **URL Substitution**: Automatically replaces `{profile}` placeholders in service URLs with detected base URL

## Database

Health check results are stored in SQLite database at `mcp/mcp-health/health-history.db`:

```sql
CREATE TABLE health_checks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  service_name TEXT NOT NULL,
  status TEXT NOT NULL,
  response_time REAL,
  error TEXT,
  http_status INTEGER,
  expected_status INTEGER,
  container_state TEXT,
  expected_state TEXT,
  active_state TEXT,
  sub_state TEXT,
  timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE alerts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  service_name TEXT NOT NULL,
  alert_type TEXT NOT NULL,
  severity TEXT NOT NULL,
  message TEXT NOT NULL,
  acknowledged BOOLEAN DEFAULT 0,
  acknowledged_at DATETIME,
  resolved BOOLEAN DEFAULT 0,
  resolved_at DATETIME,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

## Development Status

- **Phase 1 (MVP)**: ✅ Complete - Basic health check orchestration
- **Phase 2**: ✅ Complete - SQLite persistence for health history and trends
- **Phase 1+2 (Real Health Checks)**: ✅ Complete - HTTP, container, systemd checks with categorization
- **Phase 3**: ✅ Complete - Alerting and notification capabilities

**Completed Features (Phase 1+2)**:
- Real HTTP health checks using curl with expected_status validation from SSOT config
- Container health checks using docker ps with expected_state validation from SSOT config
- Systemd health checks using systemctl with expected_state validation from SSOT config
- 4-level status categorization (healthy, degraded, error, unknown)
- Profile filtering for home/mobile networks
- Category grouping in health reports (web, api, datastore, gpu, queue, optional, system)
- Recovery action suggestions from SSOT config
- Dependency analysis and cascading failure detection
- Enhanced database schema with detailed health metrics including expected values

**Completed Features (Phase 3)**:
- Alert generation based on service status changes
- Service criticality levels (critical, important, optional)
- Alert deduplication to prevent spam
- Recovery notifications when services return to healthy state
- Performance degradation alerts for slow response times
- Log-based alerting integration with system journal
- Alert acknowledgment and resolution tracking
- Historical alert analysis and filtering
- Configurable alert thresholds and channels
- Alert configuration via SSOT health config

**Critical Gap Fixed**: Implemented expected_status and expected_state validation from SSOT configuration. Previously hardcoded expectations (200 for HTTP, "running" for containers, "active" for systemd) now use config-specified values for accurate health determination across 15 HTTP services and 11 container/systemd services.

## Integration Points

- **SSOT Configuration**: Reads from `docs/ssot/infrastructure/ssot.health.yml`
- **Health Check Skill**: Calls existing `.agents/skills/health-check/SKILL.md`
- **MCP Ecosystem**: Available to all MCP-compatible tools and agents
- **Status API**: Can provide data for existing status endpoints
- **Overnight Assessment**: Health data available for system assessment reports

## Usage Examples

### Check all services
```bash
mcp_call_tool mcp-health check_health {}
```

### Check specific service
```bash
mcp_call_tool mcp-health check_health {"service": "Caddy"}
```

### Get health summary
```bash
mcp_call_tool mcp-health get_health_summary {}
```

### Get historical data
```bash
mcp_call_tool mcp-health get_health_history {"service_name": "Caddy", "limit": 50}
```

## Troubleshooting

### Server not responding
- Check MCP configuration in `~/.config/devin/mcp_config.json`
- Verify server file exists and is executable
- Check server logs for errors

### Health config not loading
- Verify `HEALTH_CONFIG` environment variable points to correct file
- Check YAML syntax in health configuration file
- Ensure URL placeholders are properly quoted: `url: "{profile}/api/health"`

### Database errors
- Check write permissions for `health-history.db`
- Verify SQLite database is not corrupted
- Ensure sufficient disk space

## Future Enhancements

- **Alerting**: Threshold-based notifications for service failures
- **Dashboard Integration**: Real-time health dashboard
- **Dependency Analysis**: Track service dependency health
- **Performance Trends**: Long-term performance analysis
- **Custom Metrics**: Support for custom health check metrics

## Related Documentation

- SSOT MCP Configuration: `docs/ssot/infrastructure/ssot.mcp.yml`
- Health Configuration: `docs/ssot/infrastructure/ssot.health.yml`
- Health Check Skill: `.agents/skills/health-check/SKILL.md`
- Implementation Plan: `docs/ssot/ssot.improvements.yml`
