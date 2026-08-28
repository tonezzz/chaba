---
category: operations
---

# Automated Testing Framework

### Test Script Structure

```bash
#!/bin/bash
# test-global-rules-and-mddb.sh

echo "=== Testing Global Rules and MDDB Search ==="

# Test 1: MDDB Search Quality
echo "Test 1: MDDB Search Quality"
curl -X POST http://tony-omen.local:11023/v1/vector-search \
  -H "Content-Type: application/json" \
  -d '{"query":"GPU memory management","limit":5,"collection":"kb-system"}' \
  | jq '.results[0].score'

# Test 2: Search Performance
echo "Test 2: Search Performance"
time curl -X POST http://tony-omen.local:11023/v1/vector-search \
  -H "Content-Type: application/json" \
  -d '{"query":"health check","limit":5}'

# Test 3: Collection Coverage
echo "Test 3: Collection Coverage"
curl -s http://tony-omen.local:11023/v1/vector-stats | jq '.collections | length'

# Test 4: Document Coverage
echo "Test 4: Document Coverage"
curl -s http://tony-omen.local:11023/v1/stats | jq '.totalDocuments'

# Test 5: SSOT Auto-Sync
echo "Test 5: SSOT Auto-Sync"
systemctl status ssot-sync.service | grep Active

# Test 6: Health Monitoring
echo "Test 6: Health Monitoring"
curl -s http://tony-omen.local:11023/health

echo "=== Testing Complete ==="
```

### Continuous Monitoring

**Metrics to Track**:
- MDDB search response times (p50, p95, p99)
- Search relevance scores (average, median)
- MDDB service uptime and health
- SSOT sync success rate
- MCP tool success rates
- Agent tool selection patterns

**Alert Thresholds**:
- Search response time > 1000ms (warning), > 2000ms (critical)
- Search relevance score < 0.30 (warning), < 0.20 (critical)
- MDDB service health check failure (critical)
- SSOT sync failure (warning)
- MCP tool failure rate > 5% (warning), > 10% (critical)

