/**
 * Optimized Database Connection Pool
 * 
 * Enhanced PostgreSQL connection pool with performance optimizations,
 * query monitoring, and connection management.
 */

import { Pool } from 'pg';
import { existsSync, readFileSync } from 'node:fs';

const ENV_PATH = '/home/tony/CascadeProjects/chaba-tony-dell/stacks/web/.env';

function loadEnv(path) {
  if (!existsSync(path)) return;
  for (const line of readFileSync(path, 'utf8').split('\n')) {
    const m = line.match(/^([A-Za-z_][A-Za-z0-9_]*)=(.*)$/);
    if (!m) continue;
    const [, key, value] = m;
    if (process.env[key] != null) continue;
    process.env[key] = value.trim().replace(/\$\$/g, '$');
  }
}

loadEnv(ENV_PATH);

const user = process.env.POSTGRES_USER || 'chaba';
const password = process.env.POSTGRES_PASSWORD || 'chabapass';
const db = process.env.POSTGRES_DB || 'chaba';
const host = process.env.POSTGRES_HOST || '127.0.0.1';
const port = process.env.POSTGRES_PORT || '5432';

// Optimized pool configuration
const poolConfig = {
  connectionString: process.env.DATABASE_URL || `postgres://${user}:${password}@${host}:${port}/${db}`,
  
  // Connection pool settings
  max: 20,                          // Maximum pool size
  min: 2,                           // Minimum pool size
  idleTimeoutMillis: 30000,         // Close idle connections after 30s
  connectionTimeoutMillis: 10000,   // Return error after 10s if connection not available
  
  // Query performance settings
  statement_timeout: 30000,          // 30 second query timeout
  query_timeout: 30000,             // 30 second query timeout
  
  // Performance optimization
  application_name: 'chaba_optimized',
  
  // Logging
  log: (msg) => {
    if (msg.level === 'error') {
      console.error('Pool error:', msg);
    }
  }
};

const pool = new Pool(poolConfig);

// Query performance monitoring
const queryMetrics = {
  totalQueries: 0,
  slowQueries: 0,
  totalExecutionTime: 0,
  queriesByType: {},
  slowQueryThreshold: 1000 // 1 second
};

/**
 * Execute query with performance monitoring
 */
export async function queryWithMonitoring(text, values, options = {}) {
  const startTime = Date.now();
  const queryType = getQueryType(text);
  
  try {
    const result = await pool.query(text, values, options);
    const executionTime = Date.now() - startTime;
    
    // Update metrics
    queryMetrics.totalQueries++;
    queryMetrics.totalExecutionTime += executionTime;
    
    if (!queryMetrics.queriesByType[queryType]) {
      queryMetrics.queriesByType[queryType] = { count: 0, totalTime: 0, maxTime: 0 };
    }
    queryMetrics.queriesByType[queryType].count++;
    queryMetrics.queriesByType[queryType].totalTime += executionTime;
    queryMetrics.queriesByType[queryType].maxTime = Math.max(
      queryMetrics.queriesByType[queryType].maxTime,
      executionTime
    );
    
    // Track slow queries
    if (executionTime > queryMetrics.slowQueryThreshold) {
      queryMetrics.slowQueries++;
      console.warn(`Slow query detected (${executionTime}ms): ${text.substring(0, 100)}...`);
    }
    
    return result;
  } catch (error) {
    const executionTime = Date.now() - startTime;
    console.error(`Query failed after ${executionTime}ms:`, error.message);
    throw error;
  }
}

/**
 * Get query type from SQL text
 */
function getQueryType(sql) {
  const upperSql = sql.trim().toUpperCase();
  if (upperSql.startsWith('SELECT')) return 'SELECT';
  if (upperSql.startsWith('INSERT')) return 'INSERT';
  if (upperSql.startsWith('UPDATE')) return 'UPDATE';
  if (upperSql.startsWith('DELETE')) return 'DELETE';
  if (upperSql.startsWith('CREATE')) return 'DDL';
  if (upperSql.startsWith('ALTER')) return 'DDL';
  if (upperSql.startsWith('DROP')) return 'DDL';
  return 'OTHER';
}

/**
 * Get query performance metrics
 */
export function getQueryMetrics() {
  const avgExecutionTime = queryMetrics.totalQueries > 0 
    ? queryMetrics.totalExecutionTime / queryMetrics.totalQueries 
    : 0;
  
  return {
    ...queryMetrics,
    avgExecutionTime: Math.round(avgExecutionTime),
    slowQueryRate: queryMetrics.totalQueries > 0 
      ? (queryMetrics.slowQueries / queryMetrics.totalQueries * 100).toFixed(2) + '%'
      : '0%'
  };
}

/**
 * Reset query metrics
 */
export function resetQueryMetrics() {
  queryMetrics.totalQueries = 0;
  queryMetrics.slowQueries = 0;
  queryMetrics.totalExecutionTime = 0;
  queryMetrics.queriesByType = {};
}

/**
 * Get pool statistics
 */
export async function getPoolStats() {
  const totalCount = pool.totalCount;
  const idleCount = pool.idleCount;
  const waitingCount = pool.waitingCount;
  
  return {
    totalConnections: totalCount,
    idleConnections: idleCount,
    activeConnections: totalCount - idleCount,
    waitingClients: waitingCount,
    utilization: totalCount > 0 ? ((totalCount - idleCount) / totalCount * 100).toFixed(2) + '%' : '0%'
  };
}

/**
 * Health check for database
 */
export async function healthCheck() {
  try {
    const client = await pool.connect();
    const result = await client.query('SELECT 1 as health');
    client.release();
    
    const poolStats = await getPoolStats();
    
    return {
      healthy: true,
      queryMetrics: getQueryMetrics(),
      poolStats
    };
  } catch (error) {
    return {
      healthy: false,
      error: error.message,
      queryMetrics: getQueryMetrics(),
      poolStats: await getPoolStats()
    };
  }
}

/**
 * Analyze slow queries and suggest optimizations
 */
export function analyzeSlowQueries() {
  const metrics = getQueryMetrics();
  const suggestions = [];
  
  // Analyze by query type
  Object.entries(metrics.queriesByType).forEach(([type, data]) => {
    const avgTime = data.totalTime / data.count;
    
    if (avgTime > 500) {
      suggestions.push({
        type,
        avgTime: Math.round(avgTime) + 'ms',
        count: data.count,
        suggestion: 'Consider adding indexes or optimizing query structure'
      });
    }
    
    if (data.count > 1000 && avgTime > 100) {
      suggestions.push({
        type,
        avgTime: Math.round(avgTime) + 'ms',
        count: data.count,
        suggestion: 'High-frequency slow query - consider caching or materialized views'
      });
    }
  });
  
  return {
    slowQueryRate: metrics.slowQueryRate,
    avgExecutionTime: metrics.avgExecutionTime + 'ms',
    suggestions
  };
}

/**
 * Optimize pool configuration based on load
 */
function optimizePoolConfig(loadFactor = 1.0) {
  const newMax = Math.min(Math.round(poolConfig.max * loadFactor), 50);
  const newMin = Math.max(Math.round(poolConfig.min * loadFactor), 1);
  
  console.log(`Optimizing pool config: max ${poolConfig.max} -> ${newMax}, min ${poolConfig.min} -> ${newMin}`);
  
  // Note: Changing pool size requires recreating the pool
  // This is for future implementation
  return { newMax, newMin };
}

// Export the pool for backward compatibility
export default pool;