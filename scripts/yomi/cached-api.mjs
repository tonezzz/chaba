/**
 * Cached API middleware for Yomi API
 * Adds Redis caching to read-heavy endpoints
 */

import cacheManager from './cache-manager.mjs';

const CACHE_TTLS = {
  conversations: 300,      // 5 minutes
  messages: 60,          // 1 minute
  daily: 300,            // 5 minutes
  health: 30,            // 30 seconds
  activity: 60,          // 1 minute
  summarization: 120,    // 2 minutes
  lastUpdated: 60        // 1 minute
};

/**
 * Cache wrapper for async functions
 */
export async function withCache(namespace, key, fetchFn, ttl = 300) {
  try {
    const cacheKey = `${namespace}:${key}`;
    const cached = await cacheManager.get('api', cacheKey);
    
    if (cached !== null) {
      console.log(`Cache HIT: ${namespace}:${key}`);
      return { data: cached, cached: true };
    }
    
    console.log(`Cache MISS: ${namespace}:${key}`);
    const data = await fetchFn();
    await cacheManager.set('api', cacheKey, data, ttl);
    return { data, cached: false };
  } catch (error) {
    console.error('Cache wrapper error:', error);
    // Fall through to fetch function on cache error
    const data = await fetchFn();
    return { data, cached: false };
  }
}

/**
 * Invalidate cache for specific patterns
 */
export async function invalidateCache(pattern) {
  try {
    await cacheManager.invalidatePattern(`api:${pattern}*`);
    console.log(`Cache invalidated: ${pattern}`);
  } catch (error) {
    console.error('Cache invalidation error:', error);
  }
}

/**
 * Cache invalidation for data updates
 */
export async function invalidateConversationsCache() {
  await invalidateCache('/api/yomi/conversations');
}

export async function invalidateMessagesCache(chatId) {
  await invalidateCache(`/api/yomi/messages?chat=${chatId}`);
}

export async function invalidateDailyCache(chatId) {
  await invalidateCache(`/api/yomi/daily?chat=${chatId}`);
}

export async function invalidateAllYomiCache() {
  await cacheManager.deleteNamespace('api');
  console.log('All Yomi API cache invalidated');
}

/**
 * Get cache statistics
 */
export function getCacheStats() {
  return cacheManager.getStats();
}