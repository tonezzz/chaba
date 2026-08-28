#!/usr/bin/env node
/**
 * Test script for cache manager
 */

import cacheManager from './cache-manager.mjs';

async function testCache() {
  console.log('Testing cache manager...');
  
  // Wait for connection
  console.log('Waiting for Redis connection...');
  await new Promise(resolve => setTimeout(resolve, 1000));
  
  if (!cacheManager.connected) {
    console.error('Redis not connected, aborting test');
    return;
  }
  
  // Test basic operations
  console.log('Testing SET operation...');
  await cacheManager.set('test', 'key1', { data: 'test value' }, 60);
  console.log('✓ SET successful');
  
  console.log('Testing GET operation...');
  const value = await cacheManager.get('test', 'key1');
  console.log('✓ GET result:', value);
  
  console.log('Testing DELETE operation...');
  await cacheManager.delete('test', 'key1');
  console.log('✓ DELETE successful');
  
  console.log('Testing getOrSet pattern...');
  const result = await cacheManager.getOrSet('test', 'key2', async () => {
    return { data: 'fetched value', timestamp: Date.now() };
  }, 30);
  console.log('✓ getOrSet result:', result);
  
  console.log('Testing cache statistics...');
  const stats = cacheManager.getStats();
  console.log('Cache stats:', stats);
  
  console.log('Testing namespace deletion...');
  await cacheManager.deleteNamespace('test');
  console.log('✓ Namespace deletion successful');
  
  console.log('Final cache statistics...');
  const finalStats = cacheManager.getStats();
  console.log('Final stats:', finalStats);
  
  await cacheManager.disconnect();
  console.log('Cache manager test completed successfully!');
}

testCache().catch(console.error);