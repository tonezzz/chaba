#!/usr/bin/env node
/**
 * Caching Performance Test
 * Tests and verifies caching system performance
 */

import cacheManager from './cache-manager.mjs';
import { CachedQueryBuilder } from './db-cache.mjs';
import pool from './yomi/db.mjs';

async function testCachingPerformance() {
  console.log('Testing caching system performance...');
  
  // Test 1: Basic cache operations
  console.log('\n=== Test 1: Basic Cache Operations ===');
  const start1 = Date.now();
  
  await cacheManager.set('test', 'perf1', { data: 'performance test' }, 60);
  const get1 = await cacheManager.get('test', 'perf1');
  const get2 = await cacheManager.get('test', 'perf1'); // Should be cache hit
  
  const end1 = Date.now();
  console.log(`Basic operations: ${end1 - start1}ms`);
  console.log(`Cache hit rate: ${cacheManager.getStats().hitRate}`);
  
  // Test 2: Database query caching
  console.log('\n=== Test 2: Database Query Caching ===');
  const start2 = Date.now();
  
  const builder = new CachedQueryBuilder(pool);
  
  // First query (cache miss)
  const result1 = await builder.conversations();
  console.log(`First query (miss): ${Date.now() - start2}ms, cached: ${result1.cached}`);
  
  // Second query (cache hit)
  const start2b = Date.now();
  const result2 = await builder.conversations();
  console.log(`Second query (hit): ${Date.now() - start2b}ms, cached: ${result2.cached}`);
  
  const end2 = Date.now();
  console.log(`Total DB cache test: ${end2 - start2}ms`);
  
  // Test 3: Cache invalidation
  console.log('\n=== Test 3: Cache Invalidation ===');
  const start3 = Date.now();
  
  await cacheManager.set('test', 'invalidate', { data: 'test' }, 60);
  await cacheManager.delete('test', 'invalidate');
  const check = await cacheManager.get('test', 'invalidate');
  
  const end3 = Date.now();
  console.log(`Invalidation test: ${end3 - start3}ms`);
  console.log(`Deleted value should be null: ${check === null ? '✓' : '✗'}`);
  
  // Test 4: Pattern-based invalidation
  console.log('\n=== Test 4: Pattern-based Invalidation ===');
  const start4 = Date.now();
  
  await cacheManager.set('test', 'pattern1', { data: 'test1' }, 60);
  await cacheManager.set('test', 'pattern2', { data: 'test2' }, 60);
  await cacheManager.invalidatePattern('test:pattern*');
  
  const check1 = await cacheManager.get('test', 'pattern1');
  const check2 = await cacheManager.get('test', 'pattern2');
  
  const end4 = Date.now();
  console.log(`Pattern invalidation: ${end4 - start4}ms`);
  console.log(`Both should be null: ${check1 === null && check2 === null ? '✓' : '✗'}`);
  
  // Test 5: Cache statistics
  console.log('\n=== Test 5: Cache Statistics ===');
  const stats = cacheManager.getStats();
  console.log('Final cache statistics:', stats);
  
  // Test 6: Performance comparison
  console.log('\n=== Test 6: Performance Comparison ===');
  
  // Uncached query
  const start5 = Date.now();
  const uncached = await pool.query(`
    SELECT chat_id AS id, name, is_group AS "isGroup", category, category_source AS "categorySource",
           unread, last_message_time AS "lastMessageTime", last_preview AS "lastPreview", summary
    FROM conversations
    ORDER BY last_message_time DESC NULLS LAST
  `);
  const uncachedTime = Date.now() - start5;
  
  // Cached query
  const start6 = Date.now();
  const cached = await builder.conversations();
  const cachedTime = Date.now() - start6;
  
  console.log(`Uncached query: ${uncachedTime}ms`);
  console.log(`Cached query: ${cachedTime}ms`);
  console.log(`Performance improvement: ${((uncachedTime - cachedTime) / uncachedTime * 100).toFixed(1)}%`);
  
  await cacheManager.disconnect();
  await pool.end();
  
  console.log('\n=== Caching Performance Test Completed ===');
  console.log('Summary:');
  console.log(`- Cache hit rate: ${stats.hitRate}`);
  console.log(`- Total operations: ${stats.hits + stats.misses + stats.sets + stats.deletes}`);
  console.log(`- Performance improvement: ${((uncachedTime - cachedTime) / uncachedTime * 100).toFixed(1)}%`);
}

testCachingPerformance().catch(console.error);