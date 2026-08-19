---
category: operations
---

# MCP Health Database Migration (SQLite → PostgreSQL)

## Context
The MCP health server was originally using SQLite for health check history storage. To unify the database architecture and enhance analytical capabilities, the system was migrated to PostgreSQL, which is already used for application data.

## Migration Details

### Database Schema Changes
- **Source:** SQLite (`mcp/mcp-health/health-history.db`)
- **Destination:** PostgreSQL `chaba` database
- **Tables:** `health_checks` and `alerts`
- **Data Migrated:** 143 health checks, 13 alerts

### Technical Changes

**Server Configuration:**
- Replaced `better-sqlite3` with `pg` library (v8.11.0)
- Updated database connection to use PostgreSQL connection pooling
- Modified all database queries from SQLite to PostgreSQL syntax
- Added async/await patterns for PostgreSQL operations
- Created compatibility layer for SQLite-like API

**Schema Differences:**
- SQLite: `INTEGER PRIMARY KEY AUTOINCREMENT` → PostgreSQL: `SERIAL PRIMARY KEY`
- SQLite: `DATETIME DEFAULT CURRENT_TIMESTAMP` → PostgreSQL: `TIMESTAMP DEFAULT CURRENT_TIMESTAMP`
- SQLite: `BOOLEAN DEFAULT 0` → PostgreSQL: `BOOLEAN DEFAULT FALSE`
- Added PostgreSQL-specific indexes for performance optimization

**Query Syntax Changes:**
- SQLite: `datetime('now', '-7 days')` → PostgreSQL: `NOW() - INTERVAL '7 days'`
- SQLite: `strftime('%Y-%m-%d', timestamp)` → PostgreSQL: `DATE(timestamp)`
- Parameter placeholders: `?` → `$1, $2, ...`

### Data Migration Process

1. **Create PostgreSQL Schema:**
   ```sql
   CREATE TABLE health_checks (
       id SERIAL PRIMARY KEY,
       service_name TEXT NOT NULL,
       status TEXT NOT NULL,
       response_time REAL,
       error TEXT,
       http_status INTEGER,
       expected_status INTEGER,
       container_state TEXT,
       expected_state TEXT,
       active_state TEXT,
       sub_state TEXT,
       is_timer BOOLEAN DEFAULT FALSE,
       timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
   );

   CREATE TABLE alerts (
       id SERIAL PRIMARY KEY,
       service_name TEXT NOT NULL,
       alert_type TEXT NOT NULL,
       severity TEXT NOT NULL,
       message TEXT NOT NULL,
       acknowledged BOOLEAN DEFAULT FALSE,
       acknowledged_at TIMESTAMP,
       resolved BOOLEAN DEFAULT FALSE,
       resolved_at TIMESTAMP,
       created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
   );
   ```

2. **Export SQLite Data:**
   ```bash
   sqlite3 health-history.db ".headers on" ".mode csv" ".output health_checks.csv" "SELECT * FROM health_checks" ".quit"
   sqlite3 health-history.db ".headers on" ".mode csv" ".output alerts.csv" "SELECT * FROM alerts" ".quit"
   ```

3. **Import to PostgreSQL:**
   ```bash
   docker cp health_checks.csv postgres:/tmp/health_checks.csv
   docker exec postgres psql -U chaba -d chaba -c "COPY health_checks FROM '/tmp/health_checks.csv' DELIMITER ',' CSV HEADER"
   ```

### Overnight Assessment Integration

**Area 13 - MCP Health Server Analysis:**
- Changed from SQLite queries to PostgreSQL container queries
- Updated syntax for PostgreSQL functions (NOW(), INTERVAL)
- Graceful fallback if PostgreSQL container unavailable

## Troubleshooting

### mcp-health server fails with `connect ECONNREFUSED 127.0.0.1:5432`

**Cause:** `mcp/mcp-health/server.js` defaults `POSTGRES_HOST` to `localhost`.

**Fix:** The `mcp-health-client.py` caller must export `POSTGRES_HOST` pointing to the host that actually runs PostgreSQL. For the `tony-dell-mcp-health` timer, Postgres lives on `tony-dell`, so `mcp-health-client.py` sets:

```python
env["POSTGRES_HOST"] = env.get("POSTGRES_HOST", "tony-dell")
env["POSTGRES_PORT"] = env.get("POSTGRES_PORT", "5432")
```

Without this, the server on `tony-omen` will crash immediately and the systemd service exits with `mcp-health: failed` and a `BrokenPipeError` in the client.

**Example PostgreSQL Query:**
```bash
docker exec postgres psql -U chaba -d chaba -c "
SELECT service_name, status, COUNT(*) as check_count, AVG(response_time) as avg_response_time
FROM health_checks 
WHERE timestamp > NOW() - INTERVAL '7 days'
GROUP BY service_name, status
ORDER BY service_name, status"
```

## Benefits

### Analytical Capabilities
- **Window Functions:** Advanced trend analysis and ranking
- **CTEs:** Complex query composition and readability
- **Better Indexing:** PostgreSQL's advanced indexing options
- **JSON Support:** Future extensibility for complex data structures

### Infrastructure Benefits
- **Unified Architecture:** Single PostgreSQL instance for all data
- **Centralized Backup:** One backup strategy for all databases
- **Better Scalability:** PostgreSQL handles growing datasets efficiently
- **Enhanced Monitoring:** Native PostgreSQL monitoring tools

### Performance Improvements
- **Query Performance:** PostgreSQL optimized for complex analytical queries
- **Connection Pooling:** Better resource management with pg library
- **Concurrent Access:** Better handling of simultaneous health checks

## Configuration

### PostgreSQL Connection
```javascript
const { Pool } = pg;
const pool = new Pool({
  host: 'localhost',
  port: 5432,
  database: 'chaba',
  user: 'chaba',
  password: process.env.POSTGRES_PASSWORD || 'chabapass',
  max: 20,
  idleTimeoutMillis: 30000,
  connectionTimeoutMillis: 2000,
});
```

### Database Initialization
```javascript
async function initializeDatabase() {
  const client = await pool.connect();
  try {
    await client.query(`CREATE TABLE IF NOT EXISTS health_checks (...)`);
    await client.query(`CREATE INDEX IF NOT EXISTS idx_health_checks_service_timestamp ON health_checks(service_name, timestamp)`);
    // ... additional indexes
  } finally {
    client.release();
  }
}
```

## Troubleshooting

### Connection Issues
- **Problem:** PostgreSQL connection refused
- **Solution:** Check if PostgreSQL container is running: `docker ps | grep postgres`
- **Solution:** Verify credentials in connection string

### Data Migration Issues
- **Problem:** CSV import fails with "invalid input syntax"
- **Solution:** Ensure column order matches table structure
- **Solution:** Check for special characters in data that need escaping

### Query Syntax Errors
- **Problem:** SQLite functions not working in PostgreSQL
- **Solution:** Update datetime functions to PostgreSQL equivalents
- **Solution:** Change parameter placeholders from `?` to `$1, $2, ...`

## Rollback Strategy

If PostgreSQL migration fails, SQLite can be used as fallback:
1. Keep `health-history.db` as backup
2. Revert `mcp/mcp-health/server.js` to use `better-sqlite3`
3. Update overnight assessment script to use SQLite queries
4. PostgreSQL and SQLite can coexist during transition period

## Related Documentation
- `mcp/mcp-health/server.js` - MCP health server implementation
- `scripts/overnight-jobs-expanded.sh` - Overnight assessment with PostgreSQL integration
- `docs/ssot/infrastructure/ssot.automation.yml` - Automation configuration
- `docs/ssot/ssot.improvements.yml` - Migration improvement entry

## Tags
- database, migration, postgresql, sqlite, mcp-health, infrastructure
