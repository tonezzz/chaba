/**
 * Database Query Caching Layer
 * Caches PostgreSQL query results using Redis to reduce database load
 */

import cacheManager from './cache-manager.mjs';

const QUERY_CACHE_TTLS = {
  conversations: 300,      // 5 minutes
  messages: 60,          // 1 minute
  summaries: 300,        // 5 minutes
  categories: 600,       // 10 minutes
  stats: 120,           // 2 minutes
  gpu_queue: 30,        // 30 seconds
  health: 30             // 30 seconds
};

/**
 * Cache wrapper for database queries
 */
export async function cachedQuery(pool, query, params, ttl = 300, namespace = 'db') {
  // Generate cache key from query and params
  const cacheKey = `${query}:${JSON.stringify(params)}`;
  
  try {
    const { data, cached } = await cacheManager.getOrSet(namespace, cacheKey, async () => {
      const result = await pool.query(query, params);
      return result;
    }, ttl);
    
    return { ...data, cached };
  } catch (error) {
    console.error('Cached query error:', error);
    // Fall through to direct query on cache error
    return await pool.query(query, params);
  }
}

/**
 * Invalidate database cache by pattern
 */
export async function invalidateDbCache(pattern) {
  try {
    await cacheManager.invalidatePattern(`db:${pattern}*`);
    console.log(`Database cache invalidated: ${pattern}`);
  } catch (error) {
    console.error('Database cache invalidation error:', error);
  }
}

/**
 * Invalidate specific database cache
 */
export async function invalidateConversationsDbCache() {
  await invalidateDbCache('conversations');
}

export async function invalidateMessagesDbCache() {
  await invalidateDbCache('messages');
}

export async function invalidateSummariesDbCache() {
  await invalidateDbCache('summaries');
}

export async function invalidateAllDbCache() {
  await cacheManager.deleteNamespace('db');
  console.log('All database cache invalidated');
}

/**
 * Cached query builder for common patterns
 */
export class CachedQueryBuilder {
  constructor(pool) {
    this.pool = pool;
  }
  
  async conversations(ttl = QUERY_CACHE_TTLS.conversations) {
    return cachedQuery(
      this.pool,
      `SELECT chat_id AS id, name, is_group AS "isGroup", category, category_source AS "categorySource",
              unread, last_message_time AS "lastMessageTime", last_preview AS "lastPreview", summary
       FROM conversations
       ORDER BY last_message_time DESC NULLS LAST`,
      [],
      ttl,
      'conversations'
    );
  }
  
  async messagesByChat(chatId, limit = 100, ttl = QUERY_CACHE_TTLS.messages) {
    return cachedQuery(
      this.pool,
      `SELECT data, media_analysis FROM messages WHERE chat_id = $1 ORDER BY delivered_time DESC LIMIT $2`,
      [chatId, limit],
      ttl,
      'messages'
    );
  }
  
  async dailySummaries(chatId, ttl = QUERY_CACHE_TTLS.summaries) {
    return cachedQuery(
      this.pool,
      `SELECT date, events, actions, topics, message_count AS "messageCount" 
       FROM daily_summaries 
       WHERE chat_id = $1 
       ORDER BY date DESC`,
      [chatId],
      ttl,
      'summaries'
    );
  }
  
  async conversationStats(ttl = QUERY_CACHE_TTLS.stats) {
    return cachedQuery(
      this.pool,
      `SELECT 
        COUNT(*) as total_conversations,
        COUNT(CASE WHEN unread > 0 THEN 1 END) as unread_conversations,
        COUNT(CASE WHEN category IS NOT NULL THEN 1 END) as categorized_conversations
       FROM conversations`,
      [],
      ttl,
      'stats'
    );
  }
  
  async gpuQueueStats(ttl = QUERY_CACHE_TTLS.gpu_queue) {
    return cachedQuery(
      this.pool,
      `SELECT 
        COUNT(*) FILTER (WHERE status = 'pending') as pending,
        COUNT(*) FILTER (WHERE status = 'running') as running,
        COUNT(*) FILTER (WHERE status = 'completed') as completed,
        COUNT(*) FILTER (WHERE status = 'failed') as failed
       FROM gpu_queue`,
      [],
      ttl,
      'gpu_queue'
    );
  }
}

/**
 * Cache warming function - pre-populate cache with common queries
 */
export async function warmCache(pool) {
  console.log('Warming database cache...');
  
  const builder = new CachedQueryBuilder(pool);
  
  try {
    // Warm conversations cache
    await builder.conversations();
    console.log('✓ Conversations cache warmed');
    
    // Warm stats cache
    await builder.conversationStats();
    console.log('✓ Stats cache warmed');
    
    // Warm GPU queue cache
    await builder.gpuQueueStats();
    console.log('✓ GPU queue cache warmed');
    
    console.log('Database cache warming completed');
  } catch (error) {
    console.error('Cache warming error:', error);
  }
}