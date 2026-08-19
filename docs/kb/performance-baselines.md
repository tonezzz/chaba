---
category: operations
---

# Performance Baselines System

## Overview

The performance baselines system provides automated performance monitoring and anomaly detection for all Chaba services. It establishes baseline metrics from historical health data and compares current performance against these baselines to detect degradation or improvement.

## Components

### 1. Baseline Collection Script

**Location:** `scripts/collect-performance-baselines.mjs`

**Purpose:** Collects performance baselines from MCP health server historical data

**Usage:**
```bash
node scripts/collect-performance-baselines.mjs
```

**Features:**
- Connects to MCP health server via stdio transport
- Collects 7 days of health history
- Calculates statistical baselines for each service:
  - Mean, median, p95, p99 response times
  - Standard deviation
  - Min/max values
  - Healthy percentage
- Marks data quality confidence (high/medium/low)
- Saves baselines to `docs/ssot/infrastructure/performance-baselines.yml`

**Baseline Quality Levels:**
- **High confidence:** 5+ healthy checks
- **Medium confidence:** 3-4 healthy checks  
- **Low confidence:** 1-2 healthy checks

### 2. Overnight Assessment Integration

**Location:** `scripts/overnight-assessment.mjs`

**Purpose:** Integrates baseline analysis into overnight assessment reports

**Features:**
- Loads baselines from YAML file
- Compares current health data against baselines
- Detects anomalies (>50% deviation)
- Identifies performance degradation (>20% deviation)
- Identifies performance improvement (>20% improvement)
- Generates structured baseline analysis report

**Anomaly Detection Thresholds:**
- **Critical anomaly:** >100% deviation from baseline
- **Warning anomaly:** 50-100% deviation from baseline
- **Degradation:** 20-50% deviation from baseline
- **Improvement:** <-20% deviation from baseline
- **Within baseline:** -20% to +20% deviation

### 3. Baseline Data File

**Location:** `docs/ssot/infrastructure/performance-baselines.yml`

**Structure:**
```yaml
baselines:
  ServiceName:
    service_name: ServiceName
    category: api|datastore|gpu|system|web|queue
    type: http|container|systemd
    total_checks: total number of checks
    healthy_checks: number of healthy checks
    healthy_percentage: percentage
    response_time:
      mean: average response time (ms)
      median: median response time (ms)
      p95: 95th percentile (ms)
      p99: 99th percentile (ms)
      min: minimum response time (ms)
      max: maximum response time (ms)
      std_dev: standard deviation (ms)
    data_quality:
      sample_size: number of healthy checks
      confidence: high|medium|low
      date_range:
        start: ISO timestamp
        end: ISO timestamp
    established: ISO timestamp when baseline was created
```

## Current Baselines

As of 2026-08-12, baselines established for 18 services:

### API Services
- **Yomi API:** 165ms median, 100% healthy
- **Yomi Summarization:** 166ms median, 100% healthy
- **Yomi Rate Limiter:** 165ms median, 100% healthy
- **Yomi Activity Status:** 157ms median, 100% healthy
- **Playlived:** 117ms median, 100% healthy
- **MDDB API:** 158ms median, 100% healthy

### Data Services
- **Weaviate:** 200ms median, 100% healthy
- **MDDB Panel:** 114ms median, 100% healthy

### GPU Services
- **Imagen2:** 138ms median, 100% healthy
- **GPU Queue:** 117ms median, 100% healthy

### System Services
- **Yomi Update All Timer:** 22ms median, 100% healthy
- **Yomi Update Active Timer:** 19ms median, 100% healthy
- **Weaviate Index Timer:** 16ms median, 100% healthy
- **Chaba Health Monitor Timer:** 17ms median, 100% healthy

### Web Services
- **Caddy:** 141ms median, 100% healthy
- **BServer:** 163ms median, 100% healthy
- **Raceman Web:** 132ms median, 100% healthy

### Optional Services
- **Frigate NVR:** 177ms median, 100% healthy

**Note:** All current baselines have low confidence due to limited historical data (single check). Baselines will improve as more health history accumulates.

## Workflow

### Establishing Baselines

1. **Run baseline collection:**
   ```bash
   node scripts/collect-performance-baselines.mjs
   ```

2. **Review baseline quality:**
   - Check confidence levels in output
   - Low confidence baselines need more data
   - High confidence baselines are reliable

3. **Update baselines periodically:**
   - Weekly for stable services
   - After major service changes
   - When significant performance changes observed

### Overnight Assessment Integration

The overnight assessment automatically:
1. Loads current baselines from YAML file
2. Compares current health data against baselines
3. Generates baseline analysis section in report
4. Flags anomalies and performance changes
5. Skips low confidence baselines in analysis

### Monitoring Baseline Quality

**Signs baselines need update:**
- Consistent anomalies in reports
- Performance changes not reflected in baselines
- Service architecture changes
- New services added to health monitoring

**When to re-establish baselines:**
- After service upgrades
- When performance characteristics change
- Every 30 days for accuracy
- When confidence level is low

## Troubleshooting

### Baseline Collection Fails

**Issue:** MCP client connection error
**Solution:** Check MCP health server is running and accessible

**Issue:** No health history data
**Solution:** Run health checks to populate database before collecting baselines

**Issue:** Low confidence for all services
**Solution:** Collect more health history data over time (run health checks regularly)

### Baseline Analysis Shows Anomalies

**Issue:** False positive anomalies
**Solution:** Check baseline confidence level, low confidence baselines may be inaccurate

**Issue:** Consistent degradation
**Solution:** Investigate service performance, may need baseline update or service optimization

**Issue:** Baseline doesn't reflect current reality
**Solution:** Re-establish baselines after service changes or performance improvements

## Future Improvements

### Enhanced Data Collection
- Increase historical data collection period (30+ days)
- Add more frequent health check runs
- Implement automated baseline refresh

### Advanced Analytics
- Trend analysis over time
- Seasonal pattern detection
- Predictive performance modeling
- Machine learning anomaly detection

### Integration
- Real-time baseline monitoring dashboard
- Automated alerting for baseline violations
- Integration with Grafana or other monitoring tools
- Performance SLO tracking and reporting

## Related Files

- `scripts/collect-performance-baselines.mjs` - Baseline collection script
- `scripts/overnight-assessment.mjs` - Assessment integration
- `docs/ssot/infrastructure/performance-baselines.yml` - Baseline data
- `mcp/mcp-health/server.js` - MCP health server
- `docs/ssot/ssot.improvements.yml` - Improvement tracking

## Dependencies

- MCP health server (mcp-health)
- MCP SDK (@modelcontextprotocol/sdk)
- YAML parser (js-yaml)
- Health history database (SQLite)

## Maintenance

**Weekly:**
- Review baseline quality and confidence levels
- Check for consistent anomalies in assessment reports
- Update baselines if significant performance changes observed

**Monthly:**
- Re-establish baselines for accuracy
- Review and update baseline thresholds
- Assess need for additional services to monitor

**Quarterly:**
- Review baseline system effectiveness
- Update documentation and procedures
- Evaluate new monitoring technologies