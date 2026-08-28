#!/usr/bin/env node
/**
 * Database Performance Dashboard
 * 
 * Provides a comprehensive dashboard for database performance monitoring,
 * integrating with the optimization tools and caching system.
 */

import pool, { healthCheck, getPoolStats, getQueryMetrics } from './db-optimized.mjs';
import { analyzeTableSizes, analyzeIndexUsage, findUnusedIndexes, generateOptimizationReport } from './db-optimizer.mjs';
import cacheManager from './cache-manager.mjs';

/**
 * Get comprehensive database performance dashboard
 */
export async function getDatabasePerformanceDashboard() {
  try {
    const [health, tableSizes, indexUsage, unusedIndexes] = await Promise.all([
      healthCheck(),
      analyzeTableSizes(),
      analyzeIndexUsage(),
      findUnusedIndexes()
    ]);
    
    let cacheStats;
    try {
      cacheStats = cacheManager.getStats();
    } catch (e) {
      cacheStats = { connected: false, error: 'Cache not available' };
    }
    
    const optimizationReport = await generateOptimizationReport();
    
    return {
      timestamp: new Date().toISOString(),
      health,
      tables: {
        total: tableSizes.length,
        largest: tableSizes.length > 0 ? tableSizes[0] : null,
        totalSize: tableSizes.reduce((sum, table) => sum + (table.size_bytes || 0), 0)
      },
      indexes: {
        total: indexUsage.length,
        unused: unusedIndexes.length,
        unusedSize: unusedIndexes.reduce((sum, idx) => {
          const sizeStr = idx.index_size;
          const sizeNum = parseInt(sizeStr.replace(/\D/g, '')) || 0;
          return sum + sizeNum;
        }, 0)
      },
      cache: cacheStats,
      optimization: optimizationReport.summary,
      recommendations: optimizationReport.recommendations
    };
  } catch (error) {
    console.error('Failed to get database performance dashboard:', error);
    throw error;
  }
}

/**
 * Get real-time query performance
 */
export async function getRealTimeQueryPerformance() {
  const queryMetrics = getQueryMetrics();
  const poolStats = await getPoolStats();
  
  return {
    timestamp: new Date().toISOString(),
    queryMetrics,
    poolStats,
    performance: {
      avgExecutionTime: queryMetrics.avgExecutionTime + 'ms',
      slowQueryRate: queryMetrics.slowQueryRate,
      totalQueries: queryMetrics.totalQueries,
      slowQueries: queryMetrics.slowQueries
    }
  };
}

/**
 * Get database health status
 */
export async function getDatabaseHealthStatus() {
  const health = await healthCheck();
  const poolStats = await getPoolStats();
  
  return {
    timestamp: new Date().toISOString(),
    health: health.healthy,
    pool: poolStats,
    metrics: health.queryMetrics
  };
}

/**
 * Get cache effectiveness for database queries
 */
export async function getCacheEffectiveness() {
  try {
    const cacheStats = cacheManager.getStats();
    const queryMetrics = getQueryMetrics();
    
    const cacheHitRate = parseFloat(cacheStats.hitRate) || 0;
    const queryEfficiency = queryMetrics.totalQueries > 0 
      ? (1 - (queryMetrics.slowQueries / queryMetrics.totalQueries)) * 100 
      : 100;
    
    return {
      timestamp: new Date().toISOString(),
      cache: cacheStats,
      database: queryMetrics,
      effectiveness: {
        cacheHitRate: cacheHitRate + '%',
        queryEfficiency: queryEfficiency.toFixed(2) + '%',
        combinedScore: ((cacheHitRate + queryEfficiency) / 2).toFixed(2) + '%'
      }
    };
  } catch (error) {
    return {
      timestamp: new Date().toISOString(),
      error: 'Cache not available',
      database: getQueryMetrics(),
      effectiveness: {
        cacheHitRate: 'N/A',
        queryEfficiency: 'N/A',
        combinedScore: 'N/A'
      }
    };
  }
}

/**
 * Get optimization opportunities
 */
export async function getOptimizationOpportunities() {
  const report = await generateOptimizationReport();
  
  return {
    timestamp: new Date().toISOString(),
    opportunities: report.recommendations,
    potentialImpact: {
      indexCleanup: report.unusedIndexes.length > 0 ? 'medium' : 'none',
      queryOptimization: report.queryAnalysis.suggestions.length > 0 ? 'high' : 'none',
      caching: parseFloat(report.summary.slowQueryRate) > 10 ? 'high' : 'low'
    }
  };
}

/**
 * Main CLI interface
 */
async function main() {
  const args = process.argv.slice(2);
  const command = args[0];
  
  if (!command) {
    console.log('Database Performance Dashboard');
    console.log('Usage: node db-performance-dashboard.mjs <command>');
    console.log('');
    console.log('Commands:');
    console.log('  dashboard          - Comprehensive performance dashboard');
    console.log('  real-time          - Real-time query performance');
    console.log('  health             - Database health status');
    console.log('  cache-effectiveness - Cache effectiveness analysis');
    console.log('  optimization       - Optimization opportunities');
    return;
  }
  
  try {
    switch (command) {
      case 'dashboard':
        const dashboard = await getDatabasePerformanceDashboard();
        console.log('Database Performance Dashboard:');
        console.log(JSON.stringify(dashboard, null, 2));
        break;
        
      case 'real-time':
        const realtime = await getRealTimeQueryPerformance();
        console.log('Real-time Query Performance:');
        console.log(JSON.stringify(realtime, null, 2));
        break;
        
      case 'health':
        const health = await getDatabaseHealthStatus();
        console.log('Database Health Status:');
        console.log(JSON.stringify(health, null, 2));
        break;
        
      case 'cache-effectiveness':
        const effectiveness = await getCacheEffectiveness();
        console.log('Cache Effectiveness Analysis:');
        console.log(JSON.stringify(effectiveness, null, 2));
        break;
        
      case 'optimization':
        const opportunities = await getOptimizationOpportunities();
        console.log('Optimization Opportunities:');
        console.log(JSON.stringify(opportunities, null, 2));
        break;
        
      default:
        console.error(`Unknown command: ${command}`);
        process.exit(1);
    }
  } catch (error) {
    console.error('Error:', error);
    process.exit(1);
  } finally {
    await pool.end();
    try {
      await cacheManager.disconnect();
    } catch (e) {
      // Cache might not be connected, ignore
    }
  }
}

// Run main function if called directly
if (import.meta.url === `file://${process.argv[1]}`) {
  main().catch(console.error);
}