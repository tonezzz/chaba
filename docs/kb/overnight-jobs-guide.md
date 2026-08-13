# Overnight Assessment Jobs Guide

## Overview
The expanded overnight assessment system provides comprehensive system health monitoring and performance analysis. It runs 13 major assessment areas covering all aspects of the Chaba infrastructure.

## What's New (Expanded from Original)
The original overnight assessment covered 8 areas. The expanded version adds 5 new comprehensive areas and enhances existing ones:

### New Assessment Areas:
1. **Comprehensive Log Analysis** - Pattern detection across Docker containers and systemd services
2. **Database Performance Deep Dive** - PostgreSQL query analysis, connection pools, Weaviate performance
3. **Network Performance Analysis** - Interface statistics, connectivity checks, DNS resolution
4. **Backup Verification** - Recent backup status, integrity checks
5. **Container Security Analysis** - Image ages, security policies, resource limits
6. **Dependency Security Audit** - Outdated packages, vulnerability scanning
7. **System Resource Deep Dive** - CPU frequency, memory patterns, disk I/O, space analysis
8. **MCP Health Server Integration** - Historical health analysis, alert patterns, dependency analysis

### Enhanced Areas:
- **Health Check Integration** - Added systemd service status checks
- **GPU & Queue Analysis** - Added job history analysis
- **Yomi System Health** - Added LINE API rate limit pattern analysis
- **Documentation Consistency** - Integrated SSOT validation
- **Configuration Validation** - Added environment variable checks

## Quick Start

### Option 1: Manual Execution (Recommended for Tonight)
```bash
cd /home/tony/CascadeProjects/chaba
./scripts/run-overnight-now.sh
```

This will:
- Start the assessment immediately in the background
- Save logs to `logs/overnight-manual-TIMESTAMP.log`
- Generate report in `reports/overnight-assessment-TIMESTAMP.md`
- Allow you to go to sleep while it runs

### Option 2: Systemd Timer (Automated Daily)
```bash
# Install the systemd service and timer
sudo cp systemd/overnight-assessment.service /etc/systemd/system/
sudo cp systemd/overnight-assessment.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable overnight-assessment.timer
sudo systemctl start overnight-assessment.timer

# Check timer status
sudo systemctl status overnight-assessment.timer
sudo systemctl list-timers
```

The timer is configured to run daily at 2:00 AM.

## Files Created

### Core Scripts
- `scripts/overnight-jobs-expanded.sh` - Main assessment script (13 assessment areas)
- `scripts/run-overnight-now.sh` - Manual execution helper script

### Systemd Configuration
- `systemd/overnight-assessment.service` - Service definition
- `systemd/overnight-assessment.timer` - Timer definition (daily 2 AM)

### Output Locations
- **Logs:** `logs/overnight-TIMESTAMP.log` or `logs/overnight-manual-TIMESTAMP.log`
- **Reports:** `reports/overnight-assessment-TIMESTAMP.md`

## Assessment Areas Breakdown

### 1. Enhanced Health Check Integration
- Calls health check API: `http://tony-omen.local:8080/api/health`
- Checks systemd services: Caddy, Yomi Fetch, Yomi Process
- Monitors Docker containers: PostgreSQL, Weaviate, Redis
- **Output:** Service status summary, critical service health

### 2. Comprehensive Log Analysis (NEW)
- Analyzes Docker container logs for error patterns
- Checks systemd service logs for failures
- Pattern detection: error, exception, fail messages
- **Output:** Error pattern detection, service-specific error logs

### 3. Database Performance Deep Dive (NEW)
- PostgreSQL query performance analysis
- Database size and growth tracking
- Connection pool status monitoring
- Weaviate node status and performance
- **Output:** Query stats, database sizes, connection metrics

### 4. Extended GPU & Queue Analysis (ENHANCED)
- GPU status via API: `http://tony-omen.local:8080/api/gpu/status`
- GPU queue status: `http://tony-omen.local:3001/api/gpu-queue/status`
- Job history analysis and pattern detection
- **Output:** GPU utilization, queue backlog, job history

### 5. Enhanced Yomi System Health (ENHANCED)
- Yomi health status: `http://tony-omen.local:8080/api/yomi/health`
- Rate limiter status and performance
- Summarization status and circuit breaker states
- LINE API rate limit pattern analysis
- **Output:** Yomi service health, rate limiter metrics, API patterns

### 6. Network Performance Analysis (NEW)
- Network interface statistics
- Connectivity checks to key endpoints
- DNS resolution performance
- **Output:** Interface stats, connectivity results, DNS timing

### 7. Backup Verification (NEW)
- Recent backup status checks
- Database backup integrity verification
- Backup age and completeness analysis
- **Output:** Backup status, integrity results, age analysis

### 8. Container Security Analysis (NEW)
- Container image age tracking
- Security policy compliance checks
- Exposed port analysis
- Container resource limit monitoring
- **Output:** Image ages, security compliance, resource usage

### 9. Dependency Security Audit (NEW)
- Outdated npm package detection
- Outdated Python package detection
- Security vulnerability scanning
- Sensitive file detection
- **Output:** Outdated packages, security findings, sensitive files

### 10. System Resource Deep Dive (NEW)
- CPU frequency and governor analysis
- Memory usage patterns and statistics
- Disk I/O performance metrics
- Disk space analysis by directory
- **Output:** CPU performance, memory stats, I/O metrics, disk usage

### 11. Documentation Consistency (ENHANCED)
- SSOT YAML validation via devin CLI
- Hostname consistency checks (.local vs IP)
- Configuration drift detection
- **Output:** SSOT validation results, hostname compliance

### 12. Configuration Validation (ENHANCED)
- YAML syntax validation for config files
- Environment variable exposure checks
- Service configuration verification
- **Output:** Config validation results, security audit

### 13. MCP Health Server Integration (NEW)
- System health score calculation (0-100 scale)
- Historical health analysis (7-day trend patterns)
- Recent alerts analysis and resolution status
- Service dependency analysis and cascading failure detection
- **Output:** Health score, historical trends, alert patterns, dependency health

## Monitoring Progress

### While Running
```bash
# Monitor the log file in real-time
tail -f logs/overnight-manual-TIMESTAMP.log

# Check if the process is still running
ps aux | grep overnight-jobs

# Check the last few lines of progress
tail -20 logs/overnight-manual-TIMESTAMP.log
```

### After Completion
```bash
# View the generated report
cat reports/overnight-assessment-TIMESTAMP.md

# Check for any errors in the log
grep -i error logs/overnight-manual-TIMESTAMP.log

# View summary of what was completed
grep "===.*===" logs/overnight-manual-TIMESTAMP.log
```

## Troubleshooting

### Script Fails to Start
```bash
# Check script permissions
ls -l scripts/overnight-jobs-expanded.sh

# Ensure it's executable
chmod +x scripts/overnight-jobs-expanded.sh

# Test syntax
bash -n scripts/overnight-jobs-expanded.sh
```

### API Endpoints Unavailable
The script will continue running even if individual APIs fail. Check the log for specific API failures:
```bash
grep "API failed" logs/overnight-manual-TIMESTAMP.log
```

### Missing Dependencies
The script uses standard Linux tools. If something is missing:
```bash
# Check for required tools
which curl docker journalctl ip host

# Install missing tools on Ubuntu/Debian
sudo apt-get install curl iproute2 iputils-ping sysstat
```

### Systemd Timer Issues
```bash
# Check timer status
sudo systemctl status overnight-assessment.timer

# View timer logs
sudo journalctl -u overnight-assessment.timer

# Manually trigger the timer
sudo systemctl start overnight-assessment.service
```

## Customization

### Change Assessment Schedule
Edit `systemd/overnight-assessment.timer`:
```ini
[Timer]
OnCalendar=*-*-* 03:30:00  # Change to 3:30 AM
```

### Add/Remove Assessment Areas
Edit `scripts/overnight-jobs-expanded.sh` and comment out or add sections as needed.

### Change Output Locations
Edit the variables at the top of `scripts/overnight-jobs-expanded.sh`:
```bash
REPORT_DIR="/path/to/your/reports"
LOG_DIR="/path/to/your/logs"
```

## Report Structure

The generated markdown report includes:
1. **Executive Summary** - Quick overview of system health
2. **13 Assessment Area Sections** - Detailed analysis for each area
3. **Health Score** - Overall system health metrics
4. **Priority Actions** - Recommended next steps
5. **Completion Checklist** - Which assessments were completed

## Best Practices

1. **Run Manual Before Sleep** - Use `run-overnight-now.sh` when going to sleep
2. **Check Report in Morning** - Review `reports/overnight-assessment-TIMESTAMP.md`
3. **Address Critical Issues** - Prioritize items in "Priority Actions" section
4. **Keep Historical Reports** - Compare trends over time
5. **Update SSOT** - If configuration issues are found, update SSOT files

## Integration with Existing Systems

This expanded assessment integrates with:
- **Health Check API** - Uses existing `http://tony-omen.local:8080/api/health`
- **GPU Queue API** - Uses existing `http://tony-omen.local:3001/api/gpu-queue/status`
- **Yomi APIs** - Uses existing Yomi health and rate limiter endpoints
- **SSOT System** - Validates SSOT YAML files via devin CLI
- **Docker Infrastructure** - Monitors existing containers (PostgreSQL, Weaviate, Redis)

## Performance Impact

- **Runtime:** Approximately 15-30 minutes depending on system load
- **Resource Usage:** Low - mostly API calls and log analysis
- **Network:** Minimal - only local API calls and DNS checks
- **Disk:** ~1-2 MB for logs, ~500 KB for reports

## Security Considerations

- Script runs as user `tony` (not root)
- No external API calls except local endpoints
- Sensitive environment variables are only checked for exposure, not logged
- Backup verification respects existing backup directory permissions
- Security scanning is read-only and non-destructive

## Future Enhancements

Potential additions for future versions:
- Historical trend analysis with graphs
- Automated alerting for critical issues
- Integration with monitoring dashboards
- Predictive failure analysis
- Automated remediation for common issues
- Comparison with previous runs to detect degradation