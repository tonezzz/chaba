---
category: operations
---

# Troubleshooting

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

