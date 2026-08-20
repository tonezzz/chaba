---
category: operations
---

# Continuous monitoring
watch -n 5 '.windsurf/check-headroom-stats.sh'

# One-time check
.windsurf/check-headroom-stats.sh
```

**Comprehensive Monitoring**:
```bash
# Full infrastructure overview
.windsurf/monitor-token-usage.sh
```

## Expected Results

### After Devin Integration

**Immediate**:
- Headroom proxy begins receiving Devin requests
- Compression statistics start accumulating
- Cache effectiveness builds over time

**Short-term** (1-2 weeks):
- Compression ratios stabilize at 30-50%
- Cache hit rates establish baseline
- Latency impact measured

**Long-term** (1+ months):
- Significant cost savings accumulation
- Performance patterns established
- Optimization opportunities identified

## Performance Benchmarks

### Expected Metrics

**Headroom Proxy**:
- Compression ratio: 30-50%
- Latency impact: <10%
- Cache hit rate: 20-40%
- Error rate: <1%

**MCP Filtering**:
- Tool reduction: 66%
- Token overhead reduction: 65-70%
- Latency impact: <5%

**Overall**:
- Token reduction: 60-80%
- Cost reduction: 60-80%
- Performance impact: <15%

## Troubleshooting

### Common Issues

**No Compression After Integration**:
- Verify ANTHROPIC_BASE_URL is set correctly
- Check Headroom proxy is receiving requests
- Review proxy stats for request count
- Restart Devin Desktop after configuration

**High Latency**:
- Check system resources
- Review proxy configuration
- Consider disabling advanced features
- Monitor with check-headroom-stats.sh

**MCP Server Issues**:
- Verify filter scripts are executable
- Check MCP server health
- Review filter configuration
- Use rollback procedures if needed

## Next Steps

### Immediate (Today)
1. Choose and apply Headroom integration method
2. Restart Devin Desktop with new configuration
3. Verify proxy is receiving traffic
4. Monitor initial compression results

### Short-term (This Week)
1. Monitor compression ratios as usage increases
2. Track token usage patterns
3. Adjust filter configurations if needed
4. Document any issues or improvements

### Medium-term (This Month)
1. Analyze cost savings effectiveness
2. Review performance impact
3. Consider additional optimizations
4. Update monitoring procedures based on learnings

