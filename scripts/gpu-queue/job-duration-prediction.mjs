/**
 * Job Duration Prediction System
 * 
 * Predicts job execution time using historical data and ML-based approaches
 * for better scheduling and resource allocation.
 */

import * as db from './db.mjs';

// Prediction models
const PREDICTION_MODELS = {
  historical: 'historical',      // Simple historical average
  weighted: 'weighted',          // Weighted average (recent jobs weighted more)
  regression: 'regression',      // Linear regression on parameters
  ensemble: 'ensemble'           // Ensemble of multiple models
};

let currentModel = PREDICTION_MODELS.weighted;

/**
 * Set prediction model
 */
export function setPredictionModel(model) {
  if (Object.values(PREDICTION_MODELS).includes(model)) {
    currentModel = model;
    console.log(`Prediction model changed to: ${model}`);
  } else {
    throw new Error(`Unknown prediction model: ${model}`);
  }
}

/**
 * Get current prediction model
 */
export function getPredictionModel() {
  return currentModel;
}

/**
 * Historical average prediction
 */
async function predictHistorical(type, params) {
  try {
    const metrics = await db.getPerformanceMetricsByType(type, 50);
    if (metrics.length > 0) {
      return metrics[0].avg_execution_time;
    }
  } catch (error) {
    console.error('Failed to get historical metrics:', error);
  }
  
  return getDefaultEstimate(type);
}

/**
 * Weighted average prediction (recent jobs weighted more)
 */
async function predictWeighted(type, params) {
  try {
    const recentJobs = await db.getRecentJobsWithMetrics(20);
    const typeJobs = recentJobs.filter(job => job.type === type && job.execution_time_ms);
    
    if (typeJobs.length === 0) {
      return getDefaultEstimate(type);
    }
    
    // Calculate weighted average (more recent = higher weight)
    let weightedSum = 0;
    let totalWeight = 0;
    
    typeJobs.forEach((job, index) => {
      const weight = index + 1; // Linear weighting
      weightedSum += job.execution_time_ms * weight;
      totalWeight += weight;
    });
    
    return weightedSum / totalWeight;
  } catch (error) {
    console.error('Failed to calculate weighted prediction:', error);
    return getDefaultEstimate(type);
  }
}

/**
 * Linear regression prediction based on parameters
 */
async function predictRegression(type, params) {
  try {
    const recentJobs = await db.getRecentJobsWithMetrics(50);
    const typeJobs = recentJobs.filter(job => job.type === type && job.execution_time_ms);
    
    if (typeJobs.length < 5) {
      return getDefaultEstimate(type);
    }
    
    // Simple linear regression based on key parameters
    // This is a simplified version - production would use proper ML libraries
    
    // Extract relevant parameters based on job type
    const getParamValue = (job) => {
      const jobParams = job.params;
      switch (type) {
        case 'embedding':
          return jobParams.batch_size || 1;
        case 'imagen2':
        case 'txt2vid':
          const resolution = jobParams.resolution || '512x512';
          const [width] = resolution.split('x').map(Number);
          return width;
        case 'llama':
          return jobParams.context_length || 2048;
        case 'yomi_summary':
          return jobParams.text_length || 1000;
        case 'yomi_daily':
          return jobParams.message_count || 10;
        default:
          return 1;
      }
    };
    
    // Calculate correlation between parameter and execution time
    const dataPoints = typeJobs.map(job => ({
      x: getParamValue(job),
      y: job.execution_time_ms
    }));
    
    // Simple linear regression: y = mx + b
    const n = dataPoints.length;
    const sumX = dataPoints.reduce((sum, p) => sum + p.x, 0);
    const sumY = dataPoints.reduce((sum, p) => sum + p.y, 0);
    const sumXY = dataPoints.reduce((sum, p) => sum + (p.x * p.y), 0);
    const sumX2 = dataPoints.reduce((sum, p) => sum + (p.x * p.x), 0);
    
    const slope = (n * sumXY - sumX * sumY) / (n * sumX2 - sumX * sumX);
    const intercept = (sumY - slope * sumX) / n;
    
    // Predict for current parameters
    const currentParam = getParamValue({ params });
    const prediction = slope * currentParam + intercept;
    
    return Math.max(prediction, 1000); // Minimum 1 second
  } catch (error) {
    console.error('Failed to calculate regression prediction:', error);
    return getDefaultEstimate(type);
  }
}

/**
 * Ensemble prediction (average of multiple models)
 */
async function predictEnsemble(type, params) {
  const predictions = await Promise.all([
    predictHistorical(type, params),
    predictWeighted(type, params),
    predictRegression(type, params)
  ]);
  
  // Remove outliers and average
  const sorted = predictions.sort((a, b) => a - b);
  const middle = sorted.slice(1, -1); // Remove min and max
  
  if (middle.length === 0) {
    return predictions[0];
  }
  
  return middle.reduce((sum, val) => sum + val, 0) / middle.length;
}

/**
 * Get default estimate for job type
 */
function getDefaultEstimate(type) {
  const estimates = {
    embedding: 5000,
    imagen2: 15000,
    txt2vid: 60000,
    cogvideo: 60000,
    llama: 3000,
    yomi_summary: 5000,
    yomi_daily: 8000,
    yomi_daily_batch: 15000
  };
  
  return estimates[type] || 10000;
}

/**
 * Main prediction function
 */
export async function predictJobDuration(type, params) {
  switch (currentModel) {
    case PREDICTION_MODELS.historical:
      return await predictHistorical(type, params);
    case PREDICTION_MODELS.weighted:
      return await predictWeighted(type, params);
    case PREDICTION_MODELS.regression:
      return await predictRegression(type, params);
    case PREDICTION_MODELS.ensemble:
      return await predictEnsemble(type, params);
    default:
      return await predictWeighted(type, params);
  }
}

/**
 * Get prediction accuracy statistics
 */
export async function getPredictionAccuracy() {
  try {
    const recentJobs = await db.getRecentJobsWithMetrics(50);
    
    if (recentJobs.length === 0) {
      return {
        totalJobs: 0,
        averageError: 0,
        accuracy: 0
      };
    }
    
    let totalError = 0;
    let accuratePredictions = 0;
    
    for (const job of recentJobs) {
      if (job.execution_time_ms) {
        const prediction = await predictJobDuration(job.type, job.params);
        const error = Math.abs(prediction - job.execution_time_ms);
        const errorPercent = (error / job.execution_time_ms) * 100;
        
        totalError += errorPercent;
        
        // Consider accurate if within 20% error
        if (errorPercent < 20) {
          accuratePredictions++;
        }
      }
    }
    
    const averageError = totalError / recentJobs.length;
    const accuracy = (accuratePredictions / recentJobs.length) * 100;
    
    return {
      totalJobs: recentJobs.length,
      averageError: averageError.toFixed(2) + '%',
      accuracy: accuracy.toFixed(2) + '%',
      model: currentModel
    };
  } catch (error) {
    console.error('Failed to get prediction accuracy:', error);
    return {
      totalJobs: 0,
      averageError: 'N/A',
      accuracy: 'N/A',
      error: error.message
    };
  }
}

/**
 * Batch prediction for multiple jobs
 */
export async function predictBatchDurations(jobs) {
  const predictions = await Promise.all(
    jobs.map(async (job) => ({
      id: job.id,
      type: job.type,
      params: job.params,
      predictedDuration: await predictJobDuration(job.type, job.params)
    }))
  );
  
  return predictions;
}

/**
 * Update prediction model based on new job completion
 */
export async function updatePredictionModel(job) {
  // In a more sophisticated system, this would retrain the model
  // For now, we just log the completion for historical tracking
  console.log(`Job ${job.id} completed in ${job.execution_time_ms}ms (type: ${job.type})`);
  
  // Could trigger model retraining here if accuracy drops below threshold
  const accuracy = await getPredictionAccuracy();
  if (parseFloat(accuracy.accuracy) < 70) {
    console.warn('Prediction accuracy below 70%, consider retraining model');
  }
}