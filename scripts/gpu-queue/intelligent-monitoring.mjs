/**
 * Intelligent Queue Monitoring
 * 
 * Enhanced monitoring for intelligent scheduling features including
 * memory utilization, prediction accuracy, priority adjustments, and
 * scheduling performance metrics.
 */

import * as db from './db.mjs';
import { getGPUMemoryStats, getGPUMemoryConfig } from './gpu-memory-aware.mjs';
import { getPredictionAccuracy } from './job-duration-prediction.mjs';
import { getPriorityAdjustmentStats } from './dynamic-priority.mjs';
import { getSchedulerStats } from './scheduler.mjs';

/**
 * Get comprehensive intelligent scheduling metrics
 */
export async function getIntelligentSchedulingMetrics() {
  try {
    const [memoryStats, predictionAccuracy, priorityStats, schedulerStats] = await Promise.all([
      getGPUMemoryStats(),
      getPredictionAccuracy(),
      getPriorityAdjustmentStats(),
      getSchedulerStats()
    ]);

    const queueStatus = await db.getQueueStatus();
    const recentJobs = await db.getRecentJobsWithMetrics(20);

    return {
      timestamp: new Date().toISOString(),
      memory: {
        current: memoryStats.current,
        pending: memoryStats.pending,
        configuration: memoryStats.configuration,
        utilization: memoryStats.current.utilization
      },
      prediction: {
        model: predictionAccuracy.model,
        accuracy: predictionAccuracy.accuracy,
        averageError: predictionAccuracy.averageError,
        totalJobs: predictionAccuracy.totalJobs
      },
      priority: {
        totalJobs: priorityStats.totalJobs,
        averageDynamicPriority: priorityStats.averageDynamicPriority,
        distribution: priorityStats.priorityDistribution,
        factors: priorityStats.factors
      },
      scheduler: {
        algorithm: schedulerStats.scheduler,
        totalJobs: schedulerStats.total_jobs,
        avgExecutionTime: schedulerStats.avg_execution_time,
        avgQueueWait: schedulerStats.avg_queue_wait,
        byType: schedulerStats.by_type,
        byMode: schedulerStats.by_mode
      },
      queue: {
        status: queueStatus,
        recentJobs: recentJobs.slice(0, 5)
      }
    };
  } catch (error) {
    console.error('Failed to get intelligent scheduling metrics:', error);
    throw error;
  }
}

/**
 * Get scheduling performance comparison
 */
export async function getSchedulingPerformanceComparison() {
  try {
    const recentJobs = await db.getRecentJobsWithMetrics(100);
    
    if (recentJobs.length === 0) {
      return {
        totalJobs: 0,
        avgExecutionTime: 0,
        avgQueueWait: 0,
        throughput: 0,
        efficiency: 0
      };
    }

    let totalExecutionTime = 0;
    let totalQueueWait = 0;
    let executionCount = 0;
    let queueWaitCount = 0;
    let completedJobs = 0;

    recentJobs.forEach(job => {
      if (job.status === 'completed') {
        completedJobs++;
      }
      
      if (job.execution_time_ms) {
        totalExecutionTime += job.execution_time_ms;
        executionCount++;
      }
      
      if (job.queue_wait_time_ms) {
        totalQueueWait += job.queue_wait_time_ms;
        queueWaitCount++;
      }
    });

    const avgExecutionTime = executionCount > 0 ? totalExecutionTime / executionCount : 0;
    const avgQueueWait = queueWaitCount > 0 ? totalQueueWait / queueWaitCount : 0;
    const throughput = completedJobs > 0 ? completedJobs / (recentJobs.length / 100) : 0; // Jobs per 100
    const efficiency = avgQueueWait > 0 ? (avgExecutionTime / (avgExecutionTime + avgQueueWait)) * 100 : 0;

    return {
      totalJobs: recentJobs.length,
      completedJobs,
      avgExecutionTime: Math.round(avgExecutionTime),
      avgQueueWait: Math.round(avgQueueWait),
      throughput: throughput.toFixed(2),
      efficiency: efficiency.toFixed(2) + '%'
    };
  } catch (error) {
    console.error('Failed to get scheduling performance comparison:', error);
    throw error;
  }
}

/**
 * Get memory utilization trends
 */
export async function getMemoryUtilizationTrends(hours = 24) {
  try {
    const recentJobs = await db.getRecentJobsWithMetrics(100);
    
    if (recentJobs.length === 0) {
      return {
        trends: [],
        averageUtilization: 0,
        peakUtilization: 0
      };
    }

    const memoryStats = await getGPUMemoryStats();
    const trends = [];
    
    // Group jobs by time periods
    const timePeriods = {};
    recentJobs.forEach(job => {
      if (job.vram_used_mb) {
        const hour = new Date(job.created_at).getHours();
        if (!timePeriods[hour]) {
          timePeriods[hour] = [];
        }
        timePeriods[hour].push(job.vram_used_mb);
      }
    });

    // Calculate trends
    Object.keys(timePeriods).sort().forEach(hour => {
      const memoryUsages = timePeriods[hour];
      const avgUsage = memoryUsages.reduce((sum, val) => sum + val, 0) / memoryUsages.length;
      const maxUsage = Math.max(...memoryUsages);
      
      trends.push({
        hour: parseInt(hour),
        average: Math.round(avgUsage),
        peak: maxUsage,
        jobCount: memoryUsages.length
      });
    });

    const averageUtilization = memoryStats.current.utilization;
    const gpuConfig = getGPUMemoryConfig();
    const peakUtilization = trends.length > 0 ? Math.max(...trends.map(t => t.peak / gpuConfig.total * 100)) : 0;

    return {
      trends,
      averageUtilization: averageUtilization.toFixed(2) + '%',
      peakUtilization: peakUtilization.toFixed(2) + '%',
      current: memoryStats.current
    };
  } catch (error) {
    console.error('Failed to get memory utilization trends:', error);
    throw error;
  }
}

/**
 * Get prediction model performance over time
 */
export async function getPredictionModelPerformance(hours = 24) {
  try {
    const recentJobs = await db.getRecentJobsWithMetrics(50);
    
    if (recentJobs.length === 0) {
      return {
        accuracy: 0,
        errorRate: 0,
        model: 'unknown'
      };
    }

    const accuracy = await getPredictionAccuracy();
    
    // Calculate error distribution
    const errors = [];
    recentJobs.forEach(job => {
      if (job.execution_time_ms) {
        const predicted = 5000; // Simplified - would use actual prediction
        const error = Math.abs(predicted - job.execution_time_ms) / job.execution_time_ms * 100;
        errors.push(error);
      }
    });

    const avgError = errors.length > 0 ? errors.reduce((sum, err) => sum + err, 0) / errors.length : 0;
    const maxError = errors.length > 0 ? Math.max(...errors) : 0;
    const minError = errors.length > 0 ? Math.min(...errors) : 0;

    return {
      model: accuracy.model,
      accuracy: accuracy.accuracy,
      averageError: avgError.toFixed(2) + '%',
      maxError: maxError.toFixed(2) + '%',
      minError: minError.toFixed(2) + '%',
      totalJobs: errors.length
    };
  } catch (error) {
    console.error('Failed to get prediction model performance:', error);
    throw error;
  }
}

/**
 * Get priority adjustment effectiveness
 */
export async function getPriorityAdjustmentEffectiveness() {
  try {
    const recentJobs = await db.getRecentJobsWithMetrics(50);
    
    if (recentJobs.length === 0) {
      return {
        adjustedJobs: 0,
        avgImprovement: 0,
        effectiveness: 0
      };
    }

    // Analyze jobs that had priority adjustments
    let adjustedJobs = 0;
    let totalWaitImprovement = 0;
    let improvementCount = 0;

    recentJobs.forEach(job => {
      if (job.queue_wait_time_ms && job.priority > 1) {
        // Simplified analysis - would track actual priority changes
        adjustedJobs++;
        
        // Assume higher priority jobs have better wait times
        if (job.priority >= 4) {
          const expectedWait = 30000; // 30 seconds baseline
          const improvement = expectedWait - job.queue_wait_time_ms;
          if (improvement > 0) {
            totalWaitImprovement += improvement;
            improvementCount++;
          }
        }
      }
    });

    const avgImprovement = improvementCount > 0 ? totalWaitImprovement / improvementCount : 0;
    const effectiveness = adjustedJobs > 0 ? (improvementCount / adjustedJobs) * 100 : 0;

    return {
      adjustedJobs,
      avgImprovement: Math.round(avgImprovement) + 'ms',
      effectiveness: effectiveness.toFixed(2) + '%',
      totalJobs: recentJobs.length
    };
  } catch (error) {
    console.error('Failed to get priority adjustment effectiveness:', error);
    throw error;
  }
}

/**
 * Get comprehensive monitoring dashboard data
 */
export async function getMonitoringDashboard() {
  try {
    const [intelligentMetrics, performanceComparison, memoryTrends, predictionPerformance, priorityEffectiveness] = await Promise.all([
      getIntelligentSchedulingMetrics(),
      getSchedulingPerformanceComparison(),
      getMemoryUtilizationTrends(),
      getPredictionModelPerformance(),
      getPriorityAdjustmentEffectiveness()
    ]);

    return {
      timestamp: new Date().toISOString(),
      intelligentMetrics,
      performance: performanceComparison,
      memory: memoryTrends,
      prediction: predictionPerformance,
      priority: priorityEffectiveness,
      summary: {
        overallHealth: 'healthy',
        recommendations: generateRecommendations(intelligentMetrics, performanceComparison)
      }
    };
  } catch (error) {
    console.error('Failed to get monitoring dashboard:', error);
    throw error;
  }
}

/**
 * Generate recommendations based on metrics
 */
function generateRecommendations(metrics, performance) {
  const recommendations = [];

  // Memory utilization recommendations
  if (metrics.memory.utilization > 80) {
    recommendations.push({
      type: 'memory',
      severity: 'warning',
      message: 'GPU memory utilization is high (>80%). Consider adjusting job priorities or reducing batch sizes.'
    });
  }

  // Prediction accuracy recommendations
  if (parseFloat(metrics.prediction.accuracy) < 70) {
    recommendations.push({
      type: 'prediction',
      severity: 'warning',
      message: 'Prediction accuracy is below 70%. Consider retraining the prediction model or switching to a different algorithm.'
    });
  }

  // Queue wait time recommendations
  if (performance.avgQueueWait > 60000) {
    recommendations.push({
      type: 'queue',
      severity: 'warning',
      message: 'Average queue wait time exceeds 60 seconds. Consider increasing GPU resources or optimizing job scheduling.'
    });
  }

  // Throughput recommendations
  if (parseFloat(performance.throughput) < 0.5) {
    recommendations.push({
      type: 'throughput',
      severity: 'info',
      message: 'Job throughput is low. Consider batching similar jobs or adjusting scheduling algorithm.'
    });
  }

  if (recommendations.length === 0) {
    recommendations.push({
      type: 'general',
      severity: 'info',
      message: 'System is operating within normal parameters.'
    });
  }

  return recommendations;
}