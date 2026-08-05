# Token Optimization Monitoring Guide

## Overview

This guide provides comprehensive monitoring procedures for the token optimization infrastructure to ensure continued effectiveness and identify areas for improvement.

## Monitoring Components

### 1. Headroom Proxy Monitoring

#### Real-Time Monitoring
**Script**: `.windsurf/check-headroom-stats.sh`
**Usage**: Run periodically to check proxy performance

```bash
# One-time check
.windsurf/check-headroom-stats.sh

# Continuous monitoring (every 5 seconds)
watch -n 5 '.windsurf/check-headroom-stats.sh'
```

**Key Metrics**:
- **API Requests**: Total requests processed
- **Compression Ratio**: Percentage of tokens saved
- **Cache Hit Rate**: Effectiveness of semantic caching
- **Latency**: Performance impact of compression
- **Cost Savings**: Dollar amount saved

#### Health Monitoring
**Endpoint**: `http://127.0.0.1:8787/health`
**Check Frequency**: Every time before starting work

```bash
curl http://127.0.0.1:8787/health
```

**Expected Status**: All checks should show "healthy"

### 2. MCP Filtering Monitoring

#### Tool Count Verification
**Method**: Use Devin's MCP tool listing
**Frequency**: Weekly

**Expected Tool Counts**:
- Yomi: 4 tools (3 essential + 1 health)
- PostgreSQL: 6 tools (5 CRUD + 1 health)
- GitHub: 8 tools (7 core + 1 health)
- GPU: 4 tools (unchanged)

#### Health Check Monitoring
**Method**: Use MCP health tools
**Frequency**: Weekly

```bash
# Check each filtered MCP server health
mcp_call_tool --server yomi --tool health
mcp_call_tool --server postgres --tool health
mcp_call_tool --server github --tool health
```

**Expected Results**: All servers should report "upstream_ok": true

### 3. Comprehensive Monitoring

**Script**: `.windsurf/monitor-token-usage.sh`
**Usage**: Run daily or weekly for comprehensive overview

```bash
.windsurf/monitor-token-usage.sh
```

**Report Sections**:
1. Headroom proxy status
2. MCP server status
3. Headroom performance metrics
4. MCP filtering effectiveness
5. Summary and next steps

## Monitoring Schedule

### Daily Monitoring
- [ ] Check Headroom proxy is running
- [ ] Verify no errors in proxy logs
- [ ] Quick stats check (request count, compression ratio)

### Weekly Monitoring
- [ ] Run comprehensive monitoring script
- [ ] Verify MCP tool counts
- [ ] Check MCP server health
- [ ] Review token usage trends
- [ ] Document any issues or anomalies

### Monthly Monitoring
- [ ] Detailed performance analysis
- [ ] Cost savings calculation
- [ ] Review filter configuration effectiveness
- [ ] Check for software updates
- [ ] Update documentation if needed

## Performance Benchmarks

### Expected Performance

#### MCP Filtering
- **Tool Reduction**: 66% (65+ → 22 tools)
- **Token Overhead Reduction**: 65-70%
- **Latency Impact**: <5% increase

#### Headroom Proxy
- **Compression Ratio**: 30-50% (varies by content type)
- **Latency Impact**: <10% increase
- **Cache Hit Rate**: 20-40% (depends on usage patterns)

### Alert Thresholds

**Warning Levels**:
- **Latency Increase**: >15% above baseline
- **Compression Ratio**: <20% (below expected)
- **Error Rate**: >5% of requests
- **Cache Hit Rate**: <10% (below expected)

**Critical Levels**:
- **Latency Increase**: >30% above baseline
- **Compression Ratio**: <10% (significantly below expected)
- **Error Rate**: >10% of requests
- **Proxy Unavailable**: More than 5 minutes

## Troubleshooting

### Headroom Proxy Issues

**Proxy Not Running**:
```bash
# Check if proxy is running
curl http://127.0.0.1:8787/health

# Restart proxy
.windsurf/start-headroom-proxy.sh
```

**No Compression Occurring**:
- Check if Devin is configured to use proxy
- Verify ANTHROPIC_BASE_URL is set correctly
- Check proxy stats for request count
- Review proxy logs for errors

**High Latency**:
- Check system resources (CPU, memory)
- Review proxy configuration
- Consider disabling advanced features
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
- Test without filtering (rollback)

## Data Collection

### Token Usage Tracking

**Manual Tracking**:
- Record daily token usage from Devin Desktop
- Track session-by-session consumption
- Note types of tasks performed
- Document any anomalies

**Automated Tracking** (via Headroom):
```bash
# Get lifetime statistics
curl http://127.0.0.1:8787/stats-history | python3 -m json.tool

# Export to CSV for analysis
curl http://127.0.0.1:8787/stats-history?format=csv > token_usage.csv
```

### Performance Metrics

**Key Metrics to Track**:
1. **Token Reduction Percentage**: (Baseline - Current) / Baseline
2. **Cost Savings**: Dollar amount saved per period
3. **Compression Ratio**: Average percentage of tokens compressed
4. **Cache Effectiveness**: Hit rate and cache-related savings
5. **Latency Impact**: Added latency from optimization

## Reporting

### Weekly Report Template

```
Token Optimization Weekly Report
================================
Date: [Date]
Period: [Week Start] - [Week End]

Headroom Proxy Status:
- Status: [Running/Stopped]
- Uptime: [X hours]
- Requests Processed: [X]
- Average Compression: [X%]
- Total Tokens Saved: [X]
- Cost Savings: $[X.XX]

MCP Filtering Status:
- Total Tools: [X] (from [X] original)
- Tool Reduction: [X%]
- Server Health: [All Healthy/Issues]

Issues Encountered:
- [List any issues]

Recommendations:
- [List any recommendations]

Next Week Focus:
- [List focus areas]
```

### Monthly Analysis Template

```
Token Optimization Monthly Analysis
===================================
Month: [Month Year]

Overall Performance:
- Total Token Reduction: [X%]
- Total Cost Savings: $[XX.XX]
- Average Compression Ratio: [X%]
- Average Latency Impact: [X%]

Trends:
- Token usage trend: [Increasing/Decreasing/Stable]
- Cost savings trend: [Increasing/Decreasing/Stable]
- Performance trend: [Improving/Stable/Degrading]

Configuration Changes:
- [List any changes made]

Issues Resolved:
- [List issues and resolutions]

Optimization Opportunities:
- [List areas for improvement]

Next Month Goals:
- [List goals]
```

## Maintenance Tasks

### Weekly Maintenance
- [ ] Check Headroom proxy logs for errors
- [ ] Verify MCP server health
- [ ] Review token usage statistics
- [ ] Document any configuration changes

### Monthly Maintenance
- [ ] Check for mcp-filter updates
- [ ] Check for Headroom proxy updates
- [ ] Review and update filter configurations
- [ ] Analyze performance trends
- [ ] Update documentation as needed

### Quarterly Maintenance
- [ ] Comprehensive performance review
- [ ] Cost-benefit analysis
- [ ] Evaluate additional optimization opportunities
- [ ] Review and update monitoring procedures
- [ ] Strategic planning for improvements

## Continuous Improvement

### Optimization Opportunities

**Short-term** (1-2 weeks):
- Fine-tune MCP filter configurations
- Adjust Headroom proxy settings
- Add missing tools if needed
- Optimize proxy mode (token vs cache)

**Medium-term** (1-2 months):
- Evaluate additional MCP servers to filter
- Consider Headroom proxy for other projects
- Implement automated alerting
- Develop custom monitoring dashboards

**Long-term** (3-6 months):
- Evaluate TokenShift for advanced governance
- Implement cross-project optimization strategies
- Develop predictive analytics for token usage
- Create automated optimization recommendations

## Documentation

### Maintain Records

**Change Log**:
- Date of configuration changes
- Reason for changes
- Expected impact
- Actual results

**Performance Log**:
- Weekly performance metrics
- Monthly analysis results
- Quarterly review outcomes

**Issue Log**:
- Issues encountered
- Resolution steps
- Prevention measures

## Conclusion

Regular monitoring ensures the token optimization infrastructure continues to deliver expected savings while maintaining performance. Use this guide to establish consistent monitoring procedures and drive continuous improvement.

## Related Documentation

- **Implementation Summary**: `token-optimization-summary.md`
- **Testing Guide**: `token-optimization-testing.md`
- **Operations Runbook**: `token-optimization-runbook.md`
- **SSOT Documentation**: `ssot.token-optimization.yml`
