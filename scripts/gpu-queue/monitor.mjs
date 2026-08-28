/**
 * GPU Monitoring and Metrics Collection
 * 
 * Collects detailed GPU performance metrics for comparative analysis
 */

import pg from 'pg';
const { Pool } = pg;

const DATABASE_URL = process.env.DATABASE_URL || 'postgres://chaba:chabapass@localhost:5432/chaba';
const pool = new Pool({ connectionString: DATABASE_URL });

let mcpGpu = null;

export function setGpuClient(gpuClient) {
  mcpGpu = gpuClient;
}

/**
 * Collect current GPU metrics
 */
export async function collectGPUMetrics() {
  if (!mcpGpu) {
    console.warn('GPU MCP client not available');
    return null;
  }

  try {
    const gpuStatus = await mcpGpu.callTool({
      name: 'mcp1_gpu_status',
      arguments: {}
    });

    return {
      timestamp: Date.now(),
      vram_used_mb: gpuStatus.vram_used_mb || 0,
      vram_free_mb: gpuStatus.vram_free_mb || 0,
      vram_total_mb: gpuStatus.vram_total_mb || 4096,
      gpu_utilization: gpuStatus.gpu_utilization || 0,
      temperature: gpuStatus.temperature || 0,
      processes: gpuStatus.processes || []
    };
  } catch (error) {
    console.error('Failed to collect GPU metrics:', error);
    return null;
  }
}

/**
 * Start continuous GPU monitoring
 */
export async function startMonitoring(intervalMs = 5000) {
  console.log(`Starting GPU monitoring (interval: ${intervalMs}ms)`);

  while (true) {
    try {
      const metrics = await collectGPUMetrics();
      if (metrics) {
        await storeGPUMetrics(metrics);
      }
      await sleep(intervalMs);
    } catch (error) {
      console.error('Monitoring error:', error);
      await sleep(intervalMs);
    }
  }
}

/**
 * Store GPU metrics in database
 */
async function storeGPUMetrics(metrics) {
  try {
    await pool.query(`
      INSERT INTO gpu_metrics 
      (timestamp, vram_used_mb, vram_free_mb, vram_total_mb, gpu_utilization, temperature, processes)
      VALUES ($1, $2, $3, $4, $5, $6, $7)
    `, [
      new Date(metrics.timestamp),
      metrics.vram_used_mb,
      metrics.vram_free_mb,
      metrics.vram_total_mb,
      metrics.gpu_utilization,
      metrics.temperature,
      JSON.stringify(metrics.processes)
    ]);
  } catch (error) {
    console.error('Failed to store GPU metrics:', error);
  }
}

/**
 * Get GPU metrics history
 */
export async function getGPUMetricsHistory(minutes = 60) {
  try {
    const result = await pool.query(`
      SELECT * FROM gpu_metrics
      WHERE timestamp > NOW() - INTERVAL '${minutes} minutes'
      ORDER BY timestamp DESC
    `);
    return result.rows;
  } catch (error) {
    console.error('Failed to get GPU metrics history:', error);
    return [];
  }
}

/**
 * Get GPU utilization statistics
 */
export async function getGPUUtilizationStats(minutes = 60) {
  try {
    const result = await pool.query(`
      SELECT 
        AVG(vram_used_mb) as avg_vram_used,
        MAX(vram_used_mb) as max_vram_used,
        MIN(vram_used_mb) as min_vram_used,
        AVG(gpu_utilization) as avg_gpu_util,
        MAX(gpu_utilization) as max_gpu_util,
        AVG(temperature) as avg_temp,
        MAX(temperature) as max_temp
      FROM gpu_metrics
      WHERE timestamp > NOW() - INTERVAL '${minutes} minutes'
    `);
    return result.rows[0] || null;
  } catch (error) {
    console.error('Failed to get GPU utilization stats:', error);
    return null;
  }
}

/**
 * Create GPU metrics table if not exists
 */
export async function createGPUMetricsTable() {
  try {
    await pool.query(`
      CREATE TABLE IF NOT EXISTS gpu_metrics (
        id SERIAL PRIMARY KEY,
        timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
        vram_used_mb INTEGER,
        vram_free_mb INTEGER,
        vram_total_mb INTEGER,
        gpu_utilization FLOAT,
        temperature FLOAT,
        processes JSONB
      )
    `);

    // Create indexes
    await pool.query(`
      CREATE INDEX IF NOT EXISTS idx_gpu_metrics_timestamp 
      ON gpu_metrics(timestamp DESC)
    `);

    console.log('GPU metrics table ready');
  } catch (error) {
    console.error('Failed to create GPU metrics table:', error);
  }
}

/**
 * Analyze GPU usage patterns
 */
export async function analyzeGPUPatterns(hours = 24) {
  try {
    const result = await pool.query(`
      SELECT 
        DATE_TRUNC('hour', timestamp) as hour,
        AVG(vram_used_mb) as avg_vram,
        MAX(vram_used_mb) as max_vram,
        AVG(gpu_utilization) as avg_util,
        COUNT(*) as sample_count
      FROM gpu_metrics
      WHERE timestamp > NOW() - INTERVAL '${hours} hours'
      GROUP BY DATE_TRUNC('hour', timestamp)
      ORDER BY hour DESC
    `);
    return result.rows;
  } catch (error) {
    console.error('Failed to analyze GPU patterns:', error);
    return [];
  }
}

/**
 * Get job-GPU correlation data
 */
export async function getJobGPUCorrelation(jobId) {
  try {
    const db = await import('./db.mjs');
    const job = await db.getJob(jobId);
    if (!job) return null;

    const result = await pool.query(`
      SELECT * FROM gpu_metrics
      WHERE timestamp BETWEEN $1 AND $2
      ORDER BY timestamp ASC
    `, [job.started_at, job.completed_at]);

    return {
      job,
      gpu_metrics: result.rows
    };
  } catch (error) {
    console.error('Failed to get job-GPU correlation:', error);
    return null;
  }
}

// Helper function
function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}
