#!/usr/bin/env node
/**
 * Database Query Optimizer
 * 
 * Analyzes database performance, identifies slow queries, suggests indexes,
 * and provides optimization recommendations.
 */

import pool from './db-optimized.mjs';

/**
 * Analyze database table sizes and row counts
 */
export async function analyzeTableSizes() {
  try {
    const result = await optimizedPool.query(`
      SELECT 
        schemaname,
        tablename,
        pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) as size,
        pg_total_relation_size(schemaname||'.'||tablename) as size_bytes,
        (SELECT n_live_tup FROM pg_stat_user_tables 
         WHERE schemaname = pg_stat_user_tables.schemaname 
         AND relname = pg_stat_user_tables.tablename) as row_count
      FROM pg_stat_user_tables
      WHERE schemaname = 'public'
      ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC
    `);
    
    return result.rows;
  } catch (error) {
    console.error('Failed to analyze table sizes:', error);
    throw error;
  }
}

/**
 * Analyze index usage and efficiency
 */
export async function analyzeIndexUsage() {
  try {
    const result = await optimizedPool.query(`
      SELECT 
        schemaname,
        tablename,
        indexname,
        idx_scan as index_scans,
        idx_tup_read as tuples_read,
        idx_tup_fetch as tuples_fetched,
        pg_size_pretty(pg_relation_size(indexrelid)) as index_size
      FROM pg_stat_user_indexes
      WHERE schemaname = 'public'
      ORDER BY idx_scan DESC
    `);
    
    return result.rows;
  } catch (error) {
    console.error('Failed to analyze index usage:', error);
    throw error;
  }
}

/**
 * Identify unused indexes
 */
export async function findUnusedIndexes() {
  try {
    const result = await optimizedPool.query(`
      SELECT 
        schemaname,
        tablename,
        indexname,
        pg_size_pretty(pg_relation_size(indexrelid)) as index_size
      FROM pg_stat_user_indexes
      WHERE schemaname = 'public'
        AND idx_scan = 0
        AND indexname NOT LIKE '%_pkey'
      ORDER BY pg_relation_size(indexrelid) DESC
    `);
    
    return result.rows;
  } catch (error) {
    console.error('Failed to find unused indexes:', error);
    throw error;
  }
}

/**
 * Analyze slow queries from pg_stat_statements
 */
export async function analyzeSlowQueries() {
  try {
    // Check if pg_stat_statements is enabled
    const extensionCheck = await optimizedPool.query(`
      SELECT EXISTS(
        SELECT 1 FROM pg_extension WHERE extname = 'pg_stat_statements'
      ) as enabled
    `);
    
    if (!extensionCheck.rows[0].enabled) {
      return { enabled: false, message: 'pg_stat_statements extension not enabled' };
    }
    
    const result = await optimizedPool.query(`
      SELECT 
        query,
        calls,
        total_time,
        mean_time,
        max_time,
        rows
      FROM pg_stat_statements
      ORDER BY mean_time DESC
      LIMIT 20
    `);
    
    return { enabled: true, queries: result.rows };
  } catch (error) {
    console.error('Failed to analyze slow queries:', error);
    return { enabled: false, error: error.message };
  }
}

/**
 * Suggest missing indexes based on query patterns
 */
export async function suggestMissingIndexes() {
  try {
    const suggestions = [];
    
    // Analyze foreign key columns that might benefit from indexes
    const fkColumns = await optimizedPool.query(`
      SELECT
        tc.table_name,
        kcu.column_name,
        ccu.table_name AS foreign_table_name,
        ccu.column_name AS foreign_column_name
      FROM information_schema.table_constraints AS tc
      JOIN information_schema.key_column_usage AS kcu
        ON tc.constraint_name = kcu.constraint_name
      JOIN information_schema.constraint_column_usage AS ccu
        ON ccu.constraint_name = tc.constraint_name
      WHERE tc.constraint_type = 'FOREIGN KEY'
        AND tc.table_schema = 'public'
    `);
    
    for (const fk of fkColumns.rows) {
      // Check if index exists on foreign key column
      const indexCheck = await optimizedPool.query(`
        SELECT EXISTS(
          SELECT 1 FROM pg_indexes
          WHERE tablename = $1
          AND indexdef LIKE $2
        ) as has_index
      `, [fk.table_name, `%${fk.column_name}%`]);
      
      if (!indexCheck.rows[0].has_index) {
        suggestions.push({
          table: fk.table_name,
          column: fk.column_name,
          reason: 'Foreign key column without index',
          suggestion: `CREATE INDEX idx_${fk.table_name}_${fk.column_name} ON ${fk.table_name}(${fk.column_name})`
        });
      }
    }
    
    // Analyze WHERE clause patterns from recent queries
    // This would require query logging or pg_stat_statements
    
    return suggestions;
  } catch (error) {
    console.error('Failed to suggest missing indexes:', error);
    throw error;
  }
}

/**
 * Get database performance statistics
 */
export async function getPerformanceStats() {
  try {
    const [tableSizes, indexUsage, queryMetrics, optimizedPoolStats] = await Promise.all([
      analyzeTableSizes(),
      analyzeIndexUsage(),
      Promise.resolve(optimizedPool.getQueryMetrics()),
      optimizedPool.getPoolStats()
    ]);
    
    return {
      timestamp: new Date().toISOString(),
      tables: tableSizes,
      indexes: indexUsage,
      queryMetrics,
      optimizedPoolStats
    };
  } catch (error) {
    console.error('Failed to get performance stats:', error);
    throw error;
  }
}

/**
 * Generate optimization report
 */
export async function generateOptimizationReport() {
  try {
    const [tableSizes, unusedIndexes, slowQueries, missingIndexes, queryMetrics] = await Promise.all([
      analyzeTableSizes(),
      findUnusedIndexes(),
      analyzeSlowQueries(),
      suggestMissingIndexes(),
      Promise.resolve(optimizedPool.getQueryMetrics())
    ]);
    
    const queryAnalysis = optimizedPool.analyzeSlowQueries();
    
    const report = {
      timestamp: new Date().toISOString(),
      summary: {
        totalTables: tableSizes.length,
        totalIndexes: tableSizes.reduce((sum, table) => sum + (table.index_count || 0), 0),
        unusedIndexes: unusedIndexes.length,
        slowQueryRate: queryAnalysis.slowQueryRate,
        avgExecutionTime: queryAnalysis.avgExecutionTime
      },
      tables: tableSizes,
      unusedIndexes,
      slowQueries,
      missingIndexes,
      queryAnalysis,
      recommendations: generateRecommendations(unusedIndexes, missingIndexes, queryAnalysis)
    };
    
    return report;
  } catch (error) {
    console.error('Failed to generate optimization report:', error);
    throw error;
  }
}

/**
 * Generate optimization recommendations
 */
function generateRecommendations(unusedIndexes, missingIndexes, queryAnalysis) {
  const recommendations = [];
  
  // Index cleanup recommendations
  if (unusedIndexes.length > 0) {
    const totalSize = unusedIndexes.reduce((sum, idx) => {
      const sizeStr = idx.index_size;
      const sizeNum = parseInt(sizeStr.replace(/\D/g, '')) || 0;
      return sum + sizeNum;
    }, 0);
    
    recommendations.push({
      priority: 'low',
      category: 'index_cleanup',
      message: `Found ${unusedIndexes.length} unused indexes (~${totalSize}KB). Consider removing to improve write performance.`,
      action: 'DROP INDEX unused_index_name;'
    });
  }
  
  // Missing index recommendations
  if (missingIndexes.length > 0) {
    recommendations.push({
      priority: 'medium',
      category: 'missing_indexes',
      message: `Found ${missingIndexes.length} columns that could benefit from indexes.`,
      action: missingIndexes.map(idx => idx.suggestion)
    });
  }
  
  // Query performance recommendations
  if (parseFloat(queryAnalysis.slowQueryRate) > 10) {
    recommendations.push({
      priority: 'high',
      category: 'query_performance',
      message: `Slow query rate is ${queryAnalysis.slowQueryRate}. Consider query optimization or caching.`,
      action: 'Review slow queries and add appropriate indexes'
    });
  }
  
  if (queryAnalysis.suggestions.length > 0) {
    recommendations.push({
      priority: 'medium',
      category: 'query_optimization',
      message: 'Specific query optimizations identified.',
      action: queryAnalysis.suggestions.map(s => s.suggestion)
    });
  }
  
  return recommendations;
}

/**
 * Main CLI interface
 */
async function main() {
  const args = process.argv.slice(2);
  const command = args[0];
  
  if (!command) {
    console.log('Database Query Optimizer');
    console.log('Usage: node db-optimizer.mjs <command>');
    console.log('');
    console.log('Commands:');
    console.log('  analyze-tables      - Analyze table sizes and row counts');
    console.log('  analyze-indexes     - Analyze index usage and efficiency');
    console.log('  unused-indexes      - Find unused indexes');
    console.log('  slow-queries        - Analyze slow queries (requires pg_stat_statements)');
    console.log('  missing-indexes     - Suggest missing indexes');
    console.log('  performance-stats   - Get comprehensive performance statistics');
    console.log('  optimization-report - Generate full optimization report');
    console.log('  health-check        - Database health check');
    return;
  }
  
  try {
    switch (command) {
      case 'analyze-tables':
        const tables = await analyzeTableSizes();
        console.log('Table Analysis:');
        console.table(tables);
        break;
        
      case 'analyze-indexes':
        const indexes = await analyzeIndexUsage();
        console.log('Index Analysis:');
        console.table(indexes);
        break;
        
      case 'unused-indexes':
        const unused = await findUnusedIndexes();
        console.log('Unused Indexes:');
        console.table(unused);
        break;
        
      case 'slow-queries':
        const slow = await analyzeSlowQueries();
        console.log('Slow Query Analysis:');
        console.log(JSON.stringify(slow, null, 2));
        break;
        
      case 'missing-indexes':
        const missing = await suggestMissingIndexes();
        console.log('Missing Index Suggestions:');
        console.table(missing);
        break;
        
      case 'performance-stats':
        const stats = await getPerformanceStats();
        console.log('Performance Statistics:');
        console.log(JSON.stringify(stats, null, 2));
        break;
        
      case 'optimization-report':
        const report = await generateOptimizationReport();
        console.log('Optimization Report:');
        console.log(JSON.stringify(report, null, 2));
        break;
        
      case 'health-check':
        const client = await optimizedPool.connect();
        const result = await client.query('SELECT 1 as health');
        client.release();
        
        const optimizedPoolStats = {
          totalConnections: optimizedPool.totalCount,
          idleConnections: optimizedPool.idleCount,
          waitingClients: optimizedPool.waitingCount
        };
        
        console.log('Database Health:');
        console.log(JSON.stringify({ healthy: true, optimizedPoolStats }, null, 2));
        break;
        
      default:
        console.error(`Unknown command: ${command}`);
        process.exit(1);
    }
  } catch (error) {
    console.error('Error:', error);
    process.exit(1);
  } finally {
    await optimizedPool.end();
  }
}

// Run main function if called directly
if (import.meta.url === `file://${process.argv[1]}`) {
  main().catch(console.error);
}