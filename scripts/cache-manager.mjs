#!/usr/bin/env node
/**
 * Cache Manager
 * 
 * Multi-layer caching system using Redis for API responses, database queries, and static assets.
 * Provides cache invalidation policies and performance monitoring.
 */

import { createClient } from 'redis';

const REDIS_URL = process.env.REDIS_URL || 'redis://localhost:6379';
const CACHE_PREFIX = 'chaba:';
const DEFAULT_TTL = 300; // 5 minutes

class CacheManager {
  constructor() {
    this.client = null;
    this.connected = false;
    this.stats = {
      hits: 0,
      misses: 0,
      sets: 0,
      deletes: 0,
      errors: 0
    };
  }

  async connect() {
    try {
      this.client = createClient({
        url: REDIS_URL,
        socket: {
          reconnectStrategy: (retries) => {
            if (retries > 10) {
              return new Error('Redis reconnection failed');
            }
            return Math.min(retries * 100, 3000);
          }
        }
      });

      this.client.on('error', (err) => {
        console.error('Redis Client Error:', err);
        this.stats.errors++;
      });

      this.client.on('connect', () => {
        console.log('Redis connected');
        this.connected = true;
      });

      this.client.on('disconnect', () => {
        console.log('Redis disconnected');
        this.connected = false;
      });

      await this.client.connect();
      return true;
    } catch (error) {
      console.error('Failed to connect to Redis:', error);
      this.connected = false;
      return false;
    }
  }

  async disconnect() {
    if (this.client) {
      await this.client.quit();
      this.connected = false;
    }
  }

  /**
   * Generate cache key with prefix
   */
  makeKey(namespace, identifier) {
    return `${CACHE_PREFIX}${namespace}:${identifier}`;
  }

  /**
   * Get value from cache
   */
  async get(namespace, identifier) {
    if (!this.connected) {
      return null;
    }

    try {
      const key = this.makeKey(namespace, identifier);
      const value = await this.client.get(key);
      
      if (value !== null) {
        this.stats.hits++;
        return JSON.parse(value);
      } else {
        this.stats.misses++;
        return null;
      }
    } catch (error) {
      console.error('Cache get error:', error);
      this.stats.errors++;
      return null;
    }
  }

  /**
   * Set value in cache with TTL
   */
  async set(namespace, identifier, value, ttl = DEFAULT_TTL) {
    if (!this.connected) {
      return false;
    }

    try {
      const key = this.makeKey(namespace, identifier);
      const serialized = JSON.stringify(value);
      await this.client.setEx(key, ttl, serialized);
      this.stats.sets++;
      return true;
    } catch (error) {
      console.error('Cache set error:', error);
      this.stats.errors++;
      return false;
    }
  }

  /**
   * Delete value from cache
   */
  async delete(namespace, identifier) {
    if (!this.connected) {
      return false;
    }

    try {
      const key = this.makeKey(namespace, identifier);
      await this.client.del(key);
      this.stats.deletes++;
      return true;
    } catch (error) {
      console.error('Cache delete error:', error);
      this.stats.errors++;
      return false;
    }
  }

  /**
   * Delete all keys in a namespace
   */
  async deleteNamespace(namespace) {
    if (!this.connected) {
      return false;
    }

    try {
      const pattern = this.makeKey(namespace, '*');
      const keys = await this.client.keys(pattern);
      
      if (keys.length > 0) {
        await this.client.del(keys);
        this.stats.deletes += keys.length;
      }
      
      return true;
    } catch (error) {
      console.error('Cache namespace delete error:', error);
      this.stats.errors++;
      return false;
    }
  }

  /**
   * Get or set pattern (cache-aside)
   */
  async getOrSet(namespace, identifier, fetchFn, ttl = DEFAULT_TTL) {
    const cached = await this.get(namespace, identifier);
    if (cached !== null) {
      return cached;
    }

    const value = await fetchFn();
    await this.set(namespace, identifier, value, ttl);
    return value;
  }

  /**
   * Invalidate cache by pattern
   */
  async invalidatePattern(pattern) {
    if (!this.connected) {
      return false;
    }

    try {
      const fullPattern = `${CACHE_PREFIX}${pattern}`;
      const keys = await this.client.keys(fullPattern);
      
      if (keys.length > 0) {
        await this.client.del(keys);
        this.stats.deletes += keys.length;
      }
      
      return true;
    } catch (error) {
      console.error('Cache pattern invalidation error:', error);
      this.stats.errors++;
      return false;
    }
  }

  /**
   * Get cache statistics
   */
  getStats() {
    const hitRate = this.stats.hits + this.stats.misses > 0 
      ? (this.stats.hits / (this.stats.hits + this.stats.misses) * 100).toFixed(2)
      : 0;
    
    return {
      ...this.stats,
      hitRate: `${hitRate}%`,
      connected: this.connected
    };
  }

  /**
   * Reset statistics
   */
  resetStats() {
    this.stats = {
      hits: 0,
      misses: 0,
      sets: 0,
      deletes: 0,
      errors: 0
    };
  }

  /**
   * Clear all cache
   */
  async clearAll() {
    if (!this.connected) {
      return false;
    }

    try {
      const pattern = `${CACHE_PREFIX}*`;
      const keys = await this.client.keys(pattern);
      
      if (keys.length > 0) {
        await this.client.del(keys);
        this.stats.deletes += keys.length;
      }
      
      return true;
    } catch (error) {
      console.error('Cache clear error:', error);
      this.stats.errors++;
      return false;
    }
  }
}

// Singleton instance
const cacheManager = new CacheManager();

// Auto-connect on module load
cacheManager.connect().catch(console.error);

export default cacheManager;