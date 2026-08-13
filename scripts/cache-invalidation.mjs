#!/usr/bin/env node
/**
 * Cache Invalidation Policies
 * Manages cache invalidation strategies and scheduled cleanup
 */

import cacheManager from './cache-manager.mjs';

const INVALIDATION_POLICIES = {
  // Time-based invalidation
  timeBased: {
    conversations: 300,      // 5 minutes
    messages: 60,          // 1 minute
    daily: 300,            // 5 minutes
    health: 30,            // 30 seconds
    stats: 120,           // 2 minutes
  },
  
  // Event-based invalidation triggers
  eventBased: {
    dataUpdate: ['conversations', 'messages', 'summaries'],
    configChange: ['api', 'health'],
    serviceRestart: ['all']
  },
  
  // Size-based invalidation
  sizeBased: {
    maxMemoryMB: 512,      // Redis max memory
    warningThreshold: 0.8,  // 80% of max memory
    criticalThreshold: 0.9  // 90% of max memory
  }
};

/**
 * Invalidate cache by namespace with policy check
 */
async function invalidateWithPolicy(namespace, reason = 'manual') {
  try {
    console.log(`Invalidating cache namespace: ${namespace} (reason: ${reason})`);
    
    // Check if namespace exists in time-based policies
    if (INVALIDATION_POLICIES.timeBased[namespace]) {
      console.log(`  - Time-based policy: ${INVALIDATION_POLICIES.timeBased[namespace]}s TTL`);
    }
    
    await cacheManager.deleteNamespace(namespace);
    console.log(`  ✓ Cache namespace ${namespace} invalidated`);
    
    return { success: true, namespace, reason };
  } catch (error) {
    console.error(`Failed to invalidate cache namespace ${namespace}:`, error);
    return { success: false, namespace, reason, error: error.message };
  }
}

/**
 * Invalidate specific cache key
 */
async function invalidateKey(namespace, key, reason = 'manual') {
  try {
    console.log(`Invalidating cache key: ${namespace}:${key} (reason: ${reason})`);
    await cacheManager.delete(namespace, key);
    console.log(`  ✓ Cache key ${namespace}:${key} invalidated`);
    
    return { success: true, namespace, key, reason };
  } catch (error) {
    console.error(`Failed to invalidate cache key ${namespace}:${key}:`, error);
    return { success: false, namespace, key, reason, error: error.message };
  }
}

/**
 * Invalidate cache by pattern
 */
async function invalidatePattern(pattern, reason = 'manual') {
  try {
    console.log(`Invalidating cache pattern: ${pattern} (reason: ${reason})`);
    await cacheManager.invalidatePattern(pattern);
    console.log(`  ✓ Cache pattern ${pattern} invalidated`);
    
    return { success: true, pattern, reason };
  } catch (error) {
    console.error(`Failed to invalidate cache pattern ${pattern}:`, error);
    return { success: false, pattern, reason, error: error.message };
  }
}

/**
 * Scheduled cache cleanup
 */
async function scheduledCleanup() {
  console.log('Running scheduled cache cleanup...');
  
  const stats = cacheManager.getStats();
  console.log('Current cache stats:', stats);
  
  // Clean up expired keys (Redis handles this automatically with TTL)
  // But we can force cleanup of specific namespaces if needed
  
  const cleanupPolicies = [
    { namespace: 'api', ttl: 300, description: 'API responses older than 5 minutes' },
    { namespace: 'db', ttl: 600, description: 'DB queries older than 10 minutes' },
    { namespace: 'test', ttl: 60, description: 'Test data older than 1 minute' }
  ];
  
  for (const policy of cleanupPolicies) {
    try {
      // Redis handles TTL automatically, but we can log current state
      console.log(`  - ${policy.namespace}: ${policy.description}`);
    } catch (error) {
      console.error(`  ✗ Error checking ${policy.namespace}:`, error);
    }
  }
  
  console.log('Scheduled cache cleanup completed');
}

/**
 * Cache health check
 */
async function cacheHealthCheck() {
  const stats = cacheManager.getStats();
  const health = {
    connected: stats.connected,
    hitRate: stats.hitRate,
    totalOperations: stats.hits + stats.misses + stats.sets + stats.deletes,
    errors: stats.errors,
    status: 'healthy'
  };
  
  // Determine health status
  if (!stats.connected) {
    health.status = 'disconnected';
  } else if (stats.errors > 10) {
    health.status = 'degraded';
  } else if (parseFloat(stats.hitRate) < 50) {
    health.status = 'low_hit_rate';
  }
  
  return health;
}

/**
 * Get cache statistics for monitoring
 */
function getCacheStatistics() {
  return cacheManager.getStats();
}

/**
 * Reset cache statistics
 */
function resetCacheStatistics() {
  cacheManager.resetStats();
  console.log('Cache statistics reset');
}

/**
 * Emergency cache clear
 */
async function emergencyCacheClear() {
  console.log('⚠️  EMERGENCY CACHE CLEAR INITIATED');
  await cacheManager.clearAll();
  console.log('✓ All cache cleared');
  return { success: true, timestamp: new Date().toISOString() };
}

/**
 * Main CLI interface
 */
async function main() {
  const args = process.argv.slice(2);
  const command = args[0];
  
  if (!command) {
    console.log('Cache Inflation Policies Manager');
    console.log('Usage: node cache-invalidation.mjs <command> [options]');
    console.log('');
    console.log('Commands:');
    console.log('  invalidate <namespace> [reason]  - Invalidate cache namespace');
    console.log('  invalidate-key <namespace> <key> [reason] - Invalidate specific key');
    console.log('  invalidate-pattern <pattern> [reason] - Invalidate by pattern');
    console.log('  cleanup - Run scheduled cleanup');
    console.log('  health - Check cache health');
    console.log('  stats - Get cache statistics');
    console.log('  reset-stats - Reset cache statistics');
    console.log('  emergency-clear - Clear all cache (emergency)');
    console.log('  policies - Show invalidation policies');
    return;
  }
  
  switch (command) {
    case 'invalidate':
      if (!args[1]) {
        console.error('Error: namespace required');
        process.exit(1);
      }
      await invalidateWithPolicy(args[1], args[2] || 'manual');
      break;
      
    case 'invalidate-key':
      if (!args[1] || !args[2]) {
        console.error('Error: namespace and key required');
        process.exit(1);
      }
      await invalidateKey(args[1], args[2], args[3] || 'manual');
      break;
      
    case 'invalidate-pattern':
      if (!args[1]) {
        console.error('Error: pattern required');
        process.exit(1);
      }
      await invalidatePattern(args[1], args[2] || 'manual');
      break;
      
    case 'cleanup':
      await scheduledCleanup();
      break;
      
    case 'health':
      const health = await cacheHealthCheck();
      console.log('Cache health:', health);
      break;
      
    case 'stats':
      const stats = getCacheStatistics();
      console.log('Cache statistics:', stats);
      break;
      
    case 'reset-stats':
      resetCacheStatistics();
      break;
      
    case 'emergency-clear':
      const result = await emergencyCacheClear();
      console.log('Result:', result);
      break;
      
    case 'policies':
      console.log('Invalidation policies:', JSON.stringify(INVALIDATION_POLICIES, null, 2));
      break;
      
    default:
      console.error(`Unknown command: ${command}`);
      process.exit(1);
  }
  
  await cacheManager.disconnect();
}

// Run main function if called directly
if (import.meta.url === `file://${process.argv[1]}`) {
  main().catch(console.error);
}

export {
  invalidateWithPolicy,
  invalidateKey,
  invalidatePattern,
  scheduledCleanup,
  cacheHealthCheck,
  getCacheStatistics,
  resetCacheStatistics,
  emergencyCacheClear,
  INVALIDATION_POLICIES
};