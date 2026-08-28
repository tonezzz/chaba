#!/usr/bin/env node
/**
 * Backup Performance Monitor
 * 
 * Analyzes backup performance metrics and provides insights on backup trends,
 * performance issues, and optimization opportunities.
 */

import { readFileSync, existsSync } from 'node:fs';
import { readdirSync, statSync } from 'node:fs';

const BACKUP_ROOT = "/home/tony/GoogleDrive/Tony AI/backup/chaba";
const METRICS_LOG = `${BACKUP_ROOT}/logs/postgres_backup_metrics.log`;

/**
 * Parse backup metrics log
 */
function parseBackupMetrics() {
  if (!existsSync(METRICS_LOG)) {
    return [];
  }

  const content = readFileSync(METRICS_LOG, 'utf8');
  const lines = content.trim().split('\n');
  
  return lines.map(line => {
    const [timestamp, duration, size] = line.split(',');
    return {
      timestamp,
      duration: parseInt(duration),
      size
    };
  }).filter(entry => entry.timestamp && entry.duration);
}

/**
 * Analyze backup performance trends
 */
function analyzeBackupTrends(metrics) {
  if (metrics.length === 0) {
    return { available: false, message: 'No backup metrics available' };
  }

  const recentMetrics = metrics.slice(-10); // Last 10 backups
  const avgDuration = recentMetrics.reduce((sum, m) => sum + m.duration, 0) / recentMetrics.length;
  const maxDuration = Math.max(...recentMetrics.map(m => m.duration));
  const minDuration = Math.min(...recentMetrics.map(m => m.duration));
  
  // Detect performance degradation
  const olderMetrics = metrics.slice(0, -10);
  let trend = 'stable';
  if (olderMetrics.length > 0) {
    const olderAvg = olderMetrics.reduce((sum, m) => sum + m.duration, 0) / olderMetrics.length;
    if (avgDuration > olderAvg * 1.2) {
      trend = 'degrading';
    } else if (avgDuration < olderAvg * 0.8) {
      trend = 'improving';
    }
  }

  return {
    available: true,
    totalBackups: metrics.length,
    recentBackups: recentMetrics.length,
    avgDuration: Math.round(avgDuration) + 's',
    maxDuration: maxDuration + 's',
    minDuration: minDuration + 's',
    trend,
    latestBackup: metrics[metrics.length - 1]
  };
}

/**
 * Check backup size trends
 */
function analyzeSizeTrends(metrics) {
  if (metrics.length === 0) {
    return { available: false };
  }

  const recentMetrics = metrics.slice(-10);
  const sizes = recentMetrics.map(m => {
    const sizeMatch = m.size.match(/(\d+\.?\d*)([KMGT]?B)/);
    if (sizeMatch) {
      const value = parseFloat(sizeMatch[1]);
      const unit = sizeMatch[2];
      const multipliers = { B: 1, KB: 1024, MB: 1024**2, GB: 1024**3 };
      return value * (multipliers[unit] || 1);
    }
    return 0;
  }).filter(s => s > 0);

  if (sizes.length === 0) {
    return { available: false, message: 'Could not parse backup sizes' };
  }

  const avgSize = sizes.reduce((sum, s) => sum + s, 0) / sizes.length;
  const maxSize = Math.max(...sizes);
  const minSize = Math.min(...sizes);

  return {
    available: true,
    avgSize: formatBytes(avgSize),
    maxSize: formatBytes(maxSize),
    minSize: formatBytes(minSize),
    growthRate: calculateGrowthRate(sizes)
  };
}

/**
 * Format bytes to human readable
 */
function formatBytes(bytes) {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

/**
 * Calculate growth rate
 */
function calculateGrowthRate(sizes) {
  if (sizes.length < 2) return 'insufficient data';
  
  const first = sizes[0];
  const last = sizes[sizes.length - 1];
  const growth = ((last - first) / first) * 100;
  
  return growth.toFixed(2) + '%';
}

/**
 * Get backup storage statistics
 */
function getBackupStorageStats() {
  const dailyDir = `${BACKUP_ROOT}/daily`;
  const weeklyDir = `${BACKUP_ROOT}/weekly`;
  const monthlyDir = `${BACKUP_ROOT}/monthly`;

  const stats = {
    daily: { count: 0, size: 0 },
    weekly: { count: 0, size: 0 },
    monthly: { count: 0, size: 0 }
  };

  for (const [dir, stat] of Object.entries([
    { path: dailyDir, key: 'daily' },
    { path: weeklyDir, key: 'weekly' },
    { path: monthlyDir, key: 'monthly' }
  ])) {
    if (existsSync(dir)) {
      const files = readdirSync(dir);
      stats[stat.key].count = files.length;
      
      for (const file of files) {
        const filePath = `${dir}/${file}`;
        const fileStat = statSync(filePath);
        stats[stat.key].size += fileStat.size;
      }
    }
  }

  return {
    daily: {
      count: stats.daily.count,
      size: formatBytes(stats.daily.size)
    },
    weekly: {
      count: stats.weekly.count,
      size: formatBytes(stats.weekly.size)
    },
    monthly: {
      count: stats.monthly.count,
      size: formatBytes(stats.monthly.size)
    },
    total: {
      count: stats.daily.count + stats.weekly.count + stats.monthly.count,
      size: formatBytes(stats.daily.size + stats.weekly.size + stats.monthly.size)
    }
  };
}

/**
 * Generate backup performance report
 */
function generateBackupReport() {
  const metrics = parseBackupMetrics();
  const performanceTrends = analyzeBackupTrends(metrics);
  const sizeTrends = analyzeSizeTrends(metrics);
  const storageStats = getBackupStorageStats();

  return {
    timestamp: new Date().toISOString(),
    performance: performanceTrends,
    size: sizeTrends,
    storage: storageStats,
    recommendations: generateRecommendations(performanceTrends, sizeTrends, storageStats)
  };
}

/**
 * Generate optimization recommendations
 */
function generateRecommendations(performance, size, storage) {
  const recommendations = [];

  // Performance recommendations
  if (performance.available && performance.trend === 'degrading') {
    recommendations.push({
      priority: 'high',
      category: 'performance',
      message: 'Backup performance is degrading over time',
      action: 'Investigate database growth, check for long-running transactions, consider incremental backups'
    });
  }

  if (performance.available && performance.avgDuration && parseInt(performance.avgDuration) > 300) {
    recommendations.push({
      priority: 'medium',
      category: 'performance',
      message: `Average backup duration is ${performance.avgDuration}`,
      action: 'Consider parallel backup, compression optimization, or incremental backups'
    });
  }

  // Size recommendations
  if (size.available && size.growthRate && parseFloat(size.growthRate) > 20) {
    recommendations.push({
      priority: 'medium',
      category: 'storage',
      message: `Database growing at ${size.growthRate} rate`,
      action: 'Review data retention policies, implement data archiving, check for unnecessary data'
    });
  }

  // Storage recommendations
  if (storage.daily.count > 30) {
    recommendations.push({
      priority: 'low',
      category: 'retention',
      message: `${storage.daily.count} daily backups exceeding 30-day retention`,
      action: 'Review backup retention policy, ensure cleanup scripts are running'
    });
  }

  if (recommendations.length === 0) {
    recommendations.push({
      priority: 'info',
      category: 'status',
      message: 'Backup system operating normally',
      action: 'Continue monitoring'
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
    console.log('Backup Performance Monitor');
    console.log('Usage: node backup-performance-monitor.mjs <command>');
    console.log('');
    console.log('Commands:');
    console.log('  report      - Comprehensive backup performance report');
    console.log('  trends      - Backup performance trends');
    console.log('  storage     - Backup storage statistics');
    console.log('  metrics     - Raw backup metrics');
    return;
  }

  try {
    switch (command) {
      case 'report':
        const report = generateBackupReport();
        console.log('Backup Performance Report:');
        console.log(JSON.stringify(report, null, 2));
        break;

      case 'trends':
        const metrics = parseBackupMetrics();
        const trends = analyzeBackupTrends(metrics);
        const sizeTrends = analyzeSizeTrends(metrics);
        console.log('Backup Performance Trends:');
        console.log(JSON.stringify({ performance: trends, size: sizeTrends }, null, 2));
        break;

      case 'storage':
        const storage = getBackupStorageStats();
        console.log('Backup Storage Statistics:');
        console.log(JSON.stringify(storage, null, 2));
        break;

      case 'metrics':
        const rawMetrics = parseBackupMetrics();
        console.log('Raw Backup Metrics:');
        console.log(JSON.stringify(rawMetrics, null, 2));
        break;

      default:
        console.error(`Unknown command: ${command}`);
        process.exit(1);
    }
  } catch (error) {
    console.error('Error:', error);
    process.exit(1);
  }
}

// Run main function if called directly
if (import.meta.url === `file://${process.argv[1]}`) {
  main().catch(console.error);
}

export { generateBackupReport, parseBackupMetrics, analyzeBackupTrends, getBackupStorageStats };
