---
category: operations
---

# Overnight Assessment Jobs Guide

## Overview
The expanded overnight assessment system provides comprehensive system health monitoring and performance analysis. It runs 14 major assessment areas covering all aspects of the Chaba infrastructure, plus automatic improvement creation for critical findings.

## What's New (Expanded from Original)
The original overnight assessment covered 8 areas. The expanded version adds 6 new comprehensive areas and enhances existing ones:

### New Assessment Areas:
1. **Comprehensive Log Analysis** - 7-day pattern detection, frequency analysis, error correlation
2. **Database Performance Deep Dive** - Historical trends, long-running queries, growth analysis
3. **Network Performance Analysis** - Interface statistics, connectivity checks, DNS resolution
4. **Backup Verification** - Recent backup status, integrity checks
5. **Container Security Analysis** - Trivy vulnerability scanning, security configuration audit
6. **Dependency Security Audit** - Outdated packages, vulnerability scanning
7. **System Resource Deep Dive** - CPU frequency, memory patterns, disk I/O, capacity planning
8. **MCP Health Server Integration** - Historical health analysis, alert patterns, dependency analysis
9. **Performance Baseline Comparison** - 7-day trend analysis, performance degradation detection

### Enhanced Areas:
- **Health Check Integration** - Added systemd service status checks
- **GPU & Queue Analysis** - Added job history analysis
- **Yomi System Health** - Added LINE API rate limit pattern analysis
- **Documentation Consistency** - Integrated SSOT validation
- **Configuration Validation** - Added environment variable checks

## Files Created

### Core Scripts
- `scripts/overnight-jobs-expanded.sh` - Main assessment script (14 assessment areas)
- `scripts/run-overnight-now.sh` - Manual execution helper script

### Systemd Configuration
- `systemd/overnight-assessment.service` - Service definition
- `systemd/overnight-assessment.timer` - Timer definition (daily 2 AM)

### Output Locations
- **Logs:** `logs/overnight-TIMESTAMP.log` or `logs/overnight-manual-TIMESTAMP.log`
- **Reports:** `reports/overnight-assessment-TIMESTAMP.md`

## Report Structure

The generated markdown report includes:
1. **Executive Summary** - Quick overview of system health
2. **14 Assessment Area Sections** - Detailed analysis for each area
3. **Health Score** - Overall system health metrics
4. **Priority Actions** - Recommended next steps
5. **Completion Checklist** - Which assessments were completed
6. **Auto-Improvement Entries** - Critical findings automatically added to SSOT

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

- **Runtime:** Approximately 15-25 minutes depending on system load and container count
- **Resource Usage:** Moderate - log analysis, Trivy scanning, PostgreSQL queries
- **Network:** Minimal - only local API calls and DNS checks
- **Disk:** ~2-3 MB for logs, ~1 MB for reports
- **CPU:** Moderate during Trivy scanning and log analysis
- **Memory:** Low to moderate during PostgreSQL queries

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

## See also

- [Overnight Jobs Areas](overnight-jobs-areas.md)
- [Overnight Jobs Customization](overnight-jobs-customization.md)
- [Overnight Jobs Monitoring](overnight-jobs-monitoring.md)
- [Overnight Jobs Quickstart](overnight-jobs-quickstart.md)
- [Overnight Jobs Troubleshooting](overnight-jobs-troubleshooting.md)
