---
category: operations
---

# Overnight System Assessment
## What it is

Automated overnight system assessment that runs comprehensive health checks and performance analysis of the Chaba infrastructure. Scheduled to run daily at 2:00 AM via systemd timer, generating detailed reports for system administrators.

## Context/Background

Created 2026-08-05 as part of Chaba infrastructure documentation.


## Overview

Automated overnight system assessment that runs comprehensive health checks and performance analysis of the Chaba infrastructure. Scheduled to run daily at 2:00 AM via systemd timer, generating detailed reports for system administrators.

## Key files

| File | Purpose |
|------|---------|
| `chaba/.agents/skills/overnight-assessment/SKILL.md` | Assessment skill definition and scope |
| `chaba/scripts/overnight-assessment.mjs` | Main assessment script (Node.js) |
| `/etc/systemd/system/chaba-assessment.timer` | Systemd timer for scheduling |
| `/etc/systemd/system/chaba-assessment.service` | Systemd service definition |
| `chaba/reports/overnight-assessment-YYYY-MM-DD.md` | Generated assessment reports |
| `chaba/reports/archive/` | Reports older than 30 days (auto-archived) |

## Issue Prioritization

### Critical Issues (🚨)
- GPU temperature > 85°C
- Core service failures (Status API, Yomi API, etc.)
- Critical endpoint unavailability

### High Priority Issues (⚠️)
- GPU temperature > 75°C
- GPU VRAM usage > 90%
- Docker container failures
- High error counts in services

### Medium Priority Issues (📋)
- GPU queue failures
- Elevated resource usage
- Configuration inconsistencies

### Low Priority Issues (💡)
- IP addresses in config files (should use .local)
- Documentation updates needed
- Minor optimization opportunities

## Report Structure

Each overnight assessment generates a markdown report with:

1. **Executive Summary**
   - Overall health score (0-100)
   - Assessment timestamp
   - Total issues found by priority
   - System status overview

2. **Health Check Results**
   - Service status table with response times
   - Docker container status
   - Individual service health checks

3. **GPU & Queue Status**
   - GPU hardware metrics
   - VRAM usage and utilization
   - Temperature monitoring
   - Active GPU processes
   - Queue statistics

4. **Yomi System Health**
   - Rate limiter performance
   - Circuit breaker states
   - Summarization service status

5. **System Resources**
   - Disk usage analysis
   - Memory and swap usage
   - System load averages

6. **Configuration Validation**
   - SSOT file checks
   - Hostname compliance
   - Configuration drift detection

7. **Improvement Recommendations**
   - Prioritized action items
   - Ongoing maintenance tasks
   - Performance optimization suggestions

## Scheduling

**Timer Configuration:**
- **Schedule:** Daily at 2:00 AM (`OnCalendar=*-*-* 02:00:00`)
- **Persistence:** Enabled (runs missed jobs on boot)
- **Accuracy:** 1 minute
- **Location:** `/etc/systemd/system/chaba-assessment.timer`

**Service Configuration:**
- **User:** tony
- **Working Directory:** `/home/tony/CascadeProjects/chaba`
- **Script:** `scripts/overnight-assessment.mjs`
- **Logs:** `logs/assessment.log` (stdout), `logs/assessment-error.log` (stderr)

## Manual Execution

To run the assessment manually:

```bash
cd /home/tony/CascadeProjects/chaba
node scripts/overnight-assessment.mjs
```

To trigger the systemd service immediately:

```bash
sudo systemctl start chaba-assessment.service
```

To check timer status:

```bash
systemctl status chaba-assessment.timer
systemctl list-timers | grep chaba
```

## Log Locations

- **Assessment logs:** `/home/tony/CascadeProjects/chaba/logs/assessment.log`
- **Error logs:** `/home/tony/CascadeProjects/chaba/logs/assessment-error.log`
- **Reports:** `/home/tony/CascadeProjects/chaba/reports/overnight-assessment-YYYY-MM-DD.md`

## Integration with Existing Infrastructure

The overnight assessment system leverages existing Chaba infrastructure:

- **Health Check APIs:** Uses existing `/api/health` endpoints
- **SSOT Configuration:** Reads from `ssot.health.home.yml`
- **GPU Monitoring:** Integrates with GPU status API
- **Yomi System:** Checks Yomi API endpoints and rate limiters
- **Docker:** Uses existing Docker Compose setup
- **Systemd:** Follows pattern of existing Yomi timers
- **Improvements Tracking:** Monitors `ssot.improvements.yml` for pending/planned/completed items

## Thresholds and Alerts

Current monitoring thresholds:

- **GPU Temperature Critical:** > 85°C
- **GPU Temperature Elevated:** > 75°C
- **GPU VRAM Critical:** > 90%
- **Disk Usage Critical:** > 80%
- **Disk Usage Elevated:** > 70%
- **High Error Count:** > 5 errors in summarization
- **High Queue Count:** > 5 queued jobs

## Maintenance

**Regular Tasks:**
- Review assessment reports weekly
- Monitor for recurring issues
- Update thresholds as needed
- Archive old reports periodically (automated — see Report Archival below)
- Adjust assessment scope based on infrastructure changes

## Report Archival

Reports are automatically archived at the end of every assessment run via `archiveOldReports()` in `scripts/overnight-assessment.mjs`.

- **Retention:** 30 days in `reports/`
- **Archive destination:** `reports/archive/`
- **Trigger:** Runs automatically at the end of each assessment (no manual action needed)
- Files older than 30 days are moved (not deleted) — recoverable if needed

**Troubleshooting:**
- Check logs in `logs/assessment-error.log` for failures
- Verify systemd timer is active: `systemctl status chaba-assessment.timer`
- Test script manually to debug issues
- Check network connectivity to monitored services
- Verify Node.js runtime is available

## Future Enhancements

Potential improvements for the assessment system:

- **Historical Trend Analysis:** Track metrics over time
- **Automated Notifications:** Email/Slack alerts for critical issues
- **Dashboard Integration:** Display results in health check dashboard
- **Performance Baselines:** Compare against historical baselines
- **Predictive Analysis:** Identify trends before they become issues
- **Custom Assessment Profiles:** Different scopes for different needs
- **Integration with Monitoring:** Correlate with Netdata/Prometheus metrics

## Tags

- **docker**: docker
- **containers**: containers
- **containerization**: containerization
- **gpu**: gpu
- **nvidia**: nvidia
- **cuda**: cuda
- **ml**: ml
- **ai**: ai
- **yomi**: yomi
- **line**: line
- **messaging**: messaging
- **conversations**: conversations
- **api**: api
- **rest**: rest
- **http**: http
- **web**: web
- **database**: database
- **postgres**: postgres
- **redis**: redis
- **mongodb**: mongodb
- **sql**: sql
- **monitoring**: monitoring
- **health**: health
- **metrics**: metrics
- **logging**: logging
- **security**: security
- **auth**: auth
- **encryption**: encryption
- **ssl**: ssl
- **performance**: performance
- **optimization**: optimization
- **caching**: caching
- **documentation**: documentation
- **kb**: kb
- **knowledge-base**: knowledge-base
- **workflow**: workflow
- **automation**: automation
- **mcp**: mcp
- **weaviate**: weaviate
- **vector**: vector
- **ssot**: ssot
- **configuration**: configuration
- **infrastructure**: infrastructure
- **2026**: 2026

## See also

- [Overnight Assessment Areas](overnight-assessment-areas.md)
- [Overnight Assessment Dot Format](overnight-assessment-dot-format.md)
- [Overnight Assessment Feedback Loop](overnight-assessment-feedback-loop.md)
- [Overnight Assessment Impact Scoring](overnight-assessment-impact-scoring.md)
- [Overnight Assessment Prioritization](overnight-assessment-prioritization.md)
