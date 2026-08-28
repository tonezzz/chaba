# Database Optimization Operations Runbook

## Overview

This runbook provides procedures for monitoring, optimizing, and maintaining PostgreSQL database performance in the Chaba infrastructure. It covers connection pooling, query optimization, caching, and backup performance monitoring.

## Prerequisites

- PostgreSQL container running: `postgres`
- Redis container running: `redis` (for caching)
- Node.js 20+ for optimization scripts
- Access to database connection credentials

## Tools and Scripts

### Database Optimization Tools

- **`scripts/db-optimized.mjs`** - Optimized connection pool with performance monitoring
- **`scripts/db-optimizer.mjs`** - Query analysis and optimization recommendations
- **`scripts/db-performance-dashboard.mjs`** - Comprehensive performance dashboard
- **`scripts/cache-manager.mjs`** - Redis-based caching layer
- **`scripts/backup-performance-monitor.mjs`** - Backup performance analysis

## Database Health Monitoring

### Check Database Health Status

```bash
node scripts/db-performance-dashboard.mjs health
```

**Expected Output:**
- Health status (healthy/unhealthy)
- Pool statistics (total, idle, active connections)
- Query metrics (total queries, slow queries, execution time)

**Troubleshooting:**
- If unhealthy: Check container status, connection pool, and database logs
- If high utilization: Increase pool size or optimize queries
- If slow queries: Run optimization analysis

### Real-time Query Performance

```bash
node scripts/db-performance-dashboard.mjs real-time
```

**Expected Output:**
- Real-time query metrics
- Pool utilization
- Performance indicators

### Cache Effectiveness Analysis

```bash
node scripts/db-performance-dashboard.mjs cache-effectiveness
```

**Expected Output:**
- Cache hit rate
- Query efficiency
- Combined performance score

## Query Optimization

### Analyze Slow Queries

```bash
node scripts/db-performance-dashboard.mjs optimization
```

**Expected Output:**
- Unused indexes (cleanup opportunities)
- Missing indexes (performance improvements)
- Slow query analysis
- Optimization recommendations

### Generate Optimization Report

```bash
node scripts/db-optimizer.mjs
```

**Report Contents:**
- Table size analysis
- Index usage statistics
- Slow query patterns
- Missing index suggestions
- Performance recommendations

### Apply Index Recommendations

**Review recommendations first:**
```bash
node scripts/db-performance-dashboard.mjs optimization
```

**Apply missing indexes:**
```sql
-- Example from recommendations
CREATE INDEX idx_media_analysis_jobs_message_id ON media_analysis_jobs(message_id);
```

**Remove unused indexes:**
```sql
-- Use caution - verify index is truly unused
DROP INDEX unused_index_name;
```

## Connection Pool Optimization

### Current Pool Configuration

**Default Settings** (from `db-optimized.mjs`):
- Max connections: 20
- Min connections: 2
- Idle timeout: 30s
- Connection timeout: 10s
- Query timeout: 30s

### Adjust Pool Size

**For high load:**
```javascript
// In db-optimized.mjs
const poolConfig = {
  max: 30,  // Increase from 20
  min: 5,   // Increase from 2
  // ... other settings
};
```

**For low load:**
```javascript
const poolConfig = {
  max: 10,  // Decrease from 20
  min: 1,   // Decrease from 2
  // ... other settings
};
```

**After changes:**
```bash
# Restart services using the pool
docker restart gpu-queue
docker restart yomi-api
```

## Caching Optimization

### Check Cache Status

```bash
# Cache is auto-connected, check connection
node scripts/db-performance-dashboard.mjs cache-effectiveness
```

**Cache Metrics:**
- Hit rate (target: > 80%)
- Misses (should be minimal for hot data)
- Connection status

### Configure Cache TTL

**Default TTL: 300s (5 minutes)**

**Adjust for different data types:**
```javascript
// In cache-manager.mjs
await cacheManager.set('namespace', 'key', value, ttl);

// Short TTL for frequently changing data
await cacheManager.set('user_sessions', 'user123', data, 60); // 1 minute

// Long TTL for static data
await cacheManager.set('config', 'app_settings', config, 3600); // 1 hour
```

### Cache Invalidation

**Invalidate specific key:**
```javascript
await cacheManager.delete('namespace', 'key');
```

**Invalidate namespace:**
```javascript
await cacheManager.deleteNamespace('user_sessions');
```

**Invalidate by pattern:**
```javascript
await cacheManager.invalidatePattern('user_sessions:*');
```

## Backup Performance Monitoring

### Check Backup Storage Statistics

```bash
node scripts/backup-performance-monitor.mjs storage
```

**Expected Output:**
- Daily/weekly/monthly backup counts
- Storage usage by backup type
- Total storage consumption

### Analyze Backup Performance Trends

```bash
node scripts/backup-performance-monitor.mjs trends
```

**Expected Output:**
- Backup duration trends
- Size growth rate
- Performance degradation detection

### Generate Comprehensive Backup Report

```bash
node scripts/backup-performance-monitor.mjs report
```

**Report Contents:**
- Performance trends
- Size analysis
- Storage statistics
- Optimization recommendations

## Performance Tuning Procedures

### Routine Performance Check (Daily)

```bash
# 1. Check database health
node scripts/db-performance-dashboard.mjs health

# 2. Check cache effectiveness
node scripts/db-performance-dashboard.mjs cache-effectiveness

# 3. Review slow queries
node scripts/db-performance-dashboard.mjs optimization
```

### Weekly Optimization Review

```bash
# 1. Generate optimization report
node scripts/db-performance-dashboard.mjs optimization

# 2. Review and apply index recommendations
# (Manual review required before applying)

# 3. Check backup performance
node scripts/backup-performance-monitor.mjs report

# 4. Review storage usage
node scripts/backup-performance-monitor.mjs storage
```

### Monthly Deep Analysis

```bash
# 1. Comprehensive performance dashboard
node scripts/db-performance-dashboard.mjs dashboard

# 2. Analyze long-term trends
node scripts/backup-performance-monitor.mjs trends

# 3. Review and adjust pool configuration
# (Based on utilization patterns)

# 4. Review cache hit rates and TTL settings
# (Adjust based on access patterns)
```

## Troubleshooting

### High Slow Query Rate

**Symptoms:**
- Slow query rate > 10%
- Average execution time > 500ms

**Actions:**
1. Run optimization analysis: `node scripts/db-performance-dashboard.mjs optimization`
2. Apply missing index recommendations
3. Review query patterns in application code
4. Consider query caching for frequently executed queries

### Low Cache Hit Rate

**Symptoms:**
- Cache hit rate < 50%
- High cache misses

**Actions:**
1. Check cache connection: `node scripts/db-performance-dashboard.mjs cache-effectiveness`
2. Review TTL settings (may be too short)
3. Check cache key patterns (may be too granular)
4. Consider increasing cache size

### High Pool Utilization

**Symptoms:**
- Pool utilization > 80%
- Waiting clients > 0

**Actions:**
1. Check for connection leaks in application code
2. Increase pool size in `db-optimized.mjs`
3. Review query execution times (optimize slow queries)
4. Consider connection pooling at application level

### Backup Performance Degradation

**Symptoms:**
- Backup duration increasing over time
- Backup size growing rapidly

**Actions:**
1. Run backup performance analysis: `node scripts/backup-performance-monitor.mjs trends`
2. Review data retention policies
3. Consider incremental backups
4. Archive old data to reduce database size

## Performance Benchmarks

### Target Performance Metrics

- **Query Execution Time:** < 100ms average
- **Slow Query Rate:** < 5%
- **Cache Hit Rate:** > 80%
- **Pool Utilization:** < 70%
- **Backup Duration:** < 60s for typical database

### Alert Thresholds

- **Critical:** Slow query rate > 20%, pool utilization > 90%
- **Warning:** Slow query rate > 10%, cache hit rate < 50%
- **Info:** Backup duration > 120s, storage usage > 80%

## Integration with Monitoring

### Health Check Integration

The database optimization tools integrate with the existing health check system:

- Database health status available via `/api/health` endpoint
- Performance metrics logged to monitoring dashboard
- Alerts triggered for performance degradation

### SSOT Integration

Database performance metrics are documented in SSOT:

- Service health checks in `ssot.health.yml`
- Performance monitoring in `ssot.services.yml`
- Backup procedures in `ssot.automation.yml`

## Maintenance Schedule

### Daily (Automated)
- Database health checks
- Cache effectiveness monitoring
- Backup performance tracking

### Weekly (Manual Review)
- Optimization report review
- Index recommendation evaluation
- Backup trend analysis

### Monthly (Manual Review)
- Comprehensive performance analysis
- Pool configuration adjustment
- Cache strategy optimization
- Backup retention policy review

## Emergency Procedures

### Database Performance Degradation

**Immediate Actions:**
1. Check database health: `node scripts/db-performance-dashboard.mjs health`
2. Identify slow queries: `node scripts/db-performance-dashboard.mjs optimization`
3. Restart database if needed: `docker restart postgres`
4. Scale up pool size temporarily

### Cache Failure

**Immediate Actions:**
1. Check Redis status: `docker ps | grep redis`
2. Restart Redis if needed: `docker restart redis`
3. Cache will auto-reconnect on next operation
4. Monitor cache effectiveness after restart

### Backup Failure

**Immediate Actions:**
1. Check backup logs: `tail -f /var/log/chaba-backup.log`
2. Verify disk space: `df -h /home/tony/GoogleDrive/Tony\ AI/backup/chaba`
3. Check PostgreSQL container: `docker ps | grep postgres`
4. Run manual backup if needed: `bash scripts/backup-manager.sh`

## References

- PostgreSQL Performance Tuning: https://www.postgresql.org/docs/current/performance-tips.html
- Redis Caching Best Practices: https://redis.io/docs/manual/patterns/
- Database Connection Pooling: https://node-postgres.com/features/pooling
- Backup Optimization: https://www.postgresql.org/docs/current/backup.html

## Change Log

- **2026-08-13**: Initial database optimization runbook created
- **2026-08-13**: Added cache integration and backup performance monitoring
- **2026-08-13**: Integrated with existing health check system
