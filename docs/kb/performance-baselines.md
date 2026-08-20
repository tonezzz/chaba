---
category: operations
---

# Performance Baselines System

## Overview

The performance baselines system provides automated performance monitoring and anomaly detection for all Chaba services. It establishes baseline metrics from historical health data and compares current performance against these baselines to detect degradation or improvement.

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

## See also

- [Performance Baselines Components](performance-baselines-components.md)
- [Performance Baselines Troubleshooting](performance-baselines-troubleshooting.md)
