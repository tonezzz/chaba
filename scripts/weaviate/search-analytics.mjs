#!/usr/bin/env node
import { appendFile, readFile, writeFile, mkdir } from 'fs/promises';
import { join } from 'path';
import { existsSync } from 'fs';

const ANALYTICS_DIR = '/home/tony/CascadeProjects/chaba/scripts/weaviate/analytics';
const SEARCH_LOG_FILE = join(ANALYTICS_DIR, 'search-logs.jsonl');
const METRICS_FILE = join(ANALYTICS_DIR, 'metrics.json');

/**
 * Search Analytics System
 * Tracks search queries, results, and user feedback for quality analysis
 */

class SearchAnalytics {
  constructor() {
    this.ensureAnalyticsDir();
  }

  async ensureAnalyticsDir() {
    if (!existsSync(ANALYTICS_DIR)) {
      await mkdir(ANALYTICS_DIR, { recursive: true });
    }
  }

  async logSearch(query, results, metadata = {}) {
    const logEntry = {
      timestamp: new Date().toISOString(),
      query: query,
      resultCount: results.length,
      resultIds: results.map(r => r.id || r._additional?.id),
      metadata: {
        chunkSize: metadata.chunkSize,
        searchTime: metadata.searchTime,
        certainty: metadata.certainty,
        ...metadata
      }
    };

    await appendFile(SEARCH_LOG_FILE, JSON.stringify(logEntry) + '\n');
    return logEntry;
  }

  async logFeedback(searchId, feedback) {
    const feedbackEntry = {
      timestamp: new Date().toISOString(),
      searchId: searchId,
      feedback: feedback
    };

    const feedbackFile = join(ANALYTICS_DIR, 'feedback.jsonl');
    await appendFile(feedbackFile, JSON.stringify(feedbackEntry) + '\n');
    return feedbackEntry;
  }

  async calculateMetrics() {
    const logs = await this.readSearchLogs();
    const feedback = await this.readFeedback();

    const metrics = {
      totalSearches: logs.length,
      totalFeedback: feedback.length,
      averageResults: 0,
      uniqueQueries: new Set(),
      queryFrequency: {},
      searchTimeStats: { min: Infinity, max: 0, avg: 0 },
      feedbackDistribution: { positive: 0, negative: 0, neutral: 0 },
      topQueries: []
    };

    if (logs.length > 0) {
      // Calculate average results
      const totalResults = logs.reduce((sum, log) => sum + log.resultCount, 0);
      metrics.averageResults = totalResults / logs.length;

      // Unique queries and frequency
      logs.forEach(log => {
        metrics.uniqueQueries.add(log.query);
        metrics.queryFrequency[log.query] = (metrics.queryFrequency[log.query] || 0) + 1;
        
        if (log.metadata.searchTime) {
          metrics.searchTimeStats.min = Math.min(metrics.searchTimeStats.min, log.metadata.searchTime);
          metrics.searchTimeStats.max = Math.max(metrics.searchTimeStats.max, log.metadata.searchTime);
        }
      });

      // Top queries
      metrics.topQueries = Object.entries(metrics.queryFrequency)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 10)
        .map(([query, count]) => ({ query, count }));

      // Average search time
      const searchTimes = logs.filter(log => log.metadata.searchTime).map(log => log.metadata.searchTime);
      if (searchTimes.length > 0) {
        metrics.searchTimeStats.avg = searchTimes.reduce((a, b) => a + b, 0) / searchTimes.length;
      }
    }

    // Feedback distribution
    feedback.forEach(entry => {
      if (entry.feedback.rating >= 4) metrics.feedbackDistribution.positive++;
      else if (entry.feedback.rating <= 2) metrics.feedbackDistribution.negative++;
      else metrics.feedbackDistribution.neutral++;
    });

    metrics.uniqueQueries = metrics.uniqueQueries.size;

    await writeFile(METRICS_FILE, JSON.stringify(metrics, null, 2));
    return metrics;
  }

  async readSearchLogs() {
    try {
      const content = await readFile(SEARCH_LOG_FILE, 'utf-8');
      return content.trim().split('\n').map(line => {
        try {
          return JSON.parse(line);
        } catch {
          return null;
        }
      }).filter(Boolean);
    } catch (error) {
      return [];
    }
  }

  async readFeedback() {
    try {
      const feedbackFile = join(ANALYTICS_DIR, 'feedback.jsonl');
      const content = await readFile(feedbackFile, 'utf-8');
      return content.trim().split('\n').map(line => {
        try {
          return JSON.parse(line);
        } catch {
          return null;
        }
      }).filter(Boolean);
    } catch (error) {
      return [];
    }
  }

  async getRecentSearches(limit = 20) {
    const logs = await this.readSearchLogs();
    return logs.slice(-limit).reverse();
  }

  async searchQualityReport() {
    const metrics = await this.calculateMetrics();
    const recentSearches = await this.getRecentSearches(10);

    console.log('=== Search Quality Report ===\n');
    console.log('Overall Metrics:');
    console.log(`  Total Searches: ${metrics.totalSearches}`);
    console.log(`  Unique Queries: ${metrics.uniqueQueries}`);
    console.log(`  Average Results: ${metrics.averageResults.toFixed(2)}`);
    console.log(`  Total Feedback: ${metrics.totalFeedback}`);
    
    console.log('\nSearch Time Performance:');
    console.log(`  Min: ${metrics.searchTimeStats.min === Infinity ? 'N/A' : metrics.searchTimeStats.min + 'ms'}`);
    console.log(`  Max: ${metrics.searchTimeStats.max === 0 ? 'N/A' : metrics.searchTimeStats.max + 'ms'}`);
    console.log(`  Avg: ${metrics.searchTimeStats.avg.toFixed(2)}ms`);
    
    console.log('\nFeedback Distribution:');
    console.log(`  Positive: ${metrics.feedbackDistribution.positive}`);
    console.log(`  Neutral: ${metrics.feedbackDistribution.neutral}`);
    console.log(`  Negative: ${metrics.feedbackDistribution.negative}`);
    
    console.log('\nTop Queries:');
    metrics.topQueries.forEach(({ query, count }) => {
      console.log(`  "${query.substring(0, 50)}...": ${count} searches`);
    });
    
    console.log('\nRecent Searches:');
    recentSearches.forEach(search => {
      console.log(`  [${search.timestamp}] "${search.query.substring(0, 40)}..." (${search.resultCount} results)`);
    });

    return metrics;
  }
}

// Example usage and testing
async function testSearchAnalytics() {
  const analytics = new SearchAnalytics();
  
  console.log('Testing Search Analytics System...\n');
  
  // Simulate some search logs
  await analytics.logSearch('GPU queue system', [{ id: '1' }, { id: '2' }], { searchTime: 15, chunkSize: 512 });
  await analytics.logSearch('Chonkie chunking', [{ id: '3' }], { searchTime: 8, chunkSize: 512 });
  await analytics.logSearch('GPU queue system', [{ id: '1' }, { id: '2' }], { searchTime: 12, chunkSize: 512 });
  
  // Simulate feedback
  await analytics.logFeedback('test-search-1', { rating: 5, comment: 'Great results!' });
  await analytics.logFeedback('test-search-2', { rating: 3, comment: 'Okay results' });
  
  // Generate report
  await analytics.searchQualityReport();
}

// Run test if called directly
if (import.meta.url === `file://${process.argv[1]}`) {
  testSearchAnalytics().catch(error => {
    console.error('Search analytics test failed:', error);
    process.exit(1);
  });
}

export { SearchAnalytics };