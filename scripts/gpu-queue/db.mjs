import pg from 'pg';

const { Pool } = pg;

// Read DATABASE_URL from environment or use default
const DATABASE_URL = process.env.DATABASE_URL || 'postgres://chaba:chabapass@localhost:5432/chaba';

const pool = new Pool({
  connectionString: DATABASE_URL,
});

// Priority mapping
const PRIORITY = {
  embedding: 4,
  txt2vid: 3,
  cogvideo: 3,
  imagen2: 2,
  yomi_summary: 2,
  yomi_daily: 2,
  yomi_daily_batch: 2,
  llama: 1,
};

// Get priority value for workload type
function getPriority(type) {
  return PRIORITY[type] || 0;
}

// Create a new job
export async function createJob(type, params) {
  const priority = getPriority(type);
  const result = await pool.query(
    `INSERT INTO gpu_queue_jobs (type, params, priority)
     VALUES ($1, $2, $3)
     RETURNING *`,
    [type, JSON.stringify(params), priority]
  );
  return result.rows[0];
}

// Get job by ID
export async function getJob(id) {
  const result = await pool.query(
    'SELECT * FROM gpu_queue_jobs WHERE id = $1',
    [id]
  );
  return result.rows[0] || null;
}

// List all jobs, optionally filtered by status
export async function listJobs(status = null) {
  let query = 'SELECT * FROM gpu_queue_jobs';
  const params = [];

  if (status) {
    query += ' WHERE status = $1 ORDER BY priority DESC, created_at ASC';
    params.push(status);
  } else {
    query += ' ORDER BY created_at DESC';
  }

  const result = await pool.query(query, params);
  return result.rows;
}

// Get next pending job (highest priority first)
export async function getNextPendingJob() {
  const result = await pool.query(
    `SELECT * FROM gpu_queue_jobs
     WHERE status = 'pending'
     ORDER BY priority DESC, created_at ASC
     LIMIT 1`
  );
  return result.rows[0] || null;
}

// Update job status
export async function updateJobStatus(id, status, error = null) {
  const updates = ['status = $1'];
  const values = [status];
  let paramIndex = 2;

  if (status === 'running') {
    updates.push(`started_at = NOW()`);
  } else if (status === 'completed' || status === 'failed' || status === 'cancelled') {
    updates.push(`completed_at = NOW()`);
  }

  if (error) {
    updates.push(`error = $${paramIndex}`);
    values.push(error);
    paramIndex++;
  }

  values.push(id);

  const query = `
    UPDATE gpu_queue_jobs
    SET ${updates.join(', ')}
    WHERE id = $${paramIndex}
    RETURNING *
  `;

  const result = await pool.query(query, values);
  return result.rows[0];
}

// Update job priority
export async function updateJobPriority(id, priority) {
  const result = await pool.query(
    `UPDATE gpu_queue_jobs
     SET priority = $1
     WHERE id = $2
     RETURNING *`,
    [priority, id]
  );
  return result.rows[0];
}

// Update job metrics (for performance tracking)
export async function updateJobMetrics(id, metrics) {
  const {
    execution_time_ms,
    gpu_used,
    vram_used_mb,
    mode,
    batch_size,
    queue_wait_time_ms,
    result
  } = metrics;

  const updates = [];
  const values = [];
  let paramIndex = 1;

  if (execution_time_ms !== undefined) {
    updates.push(`execution_time_ms = $${paramIndex}`);
    values.push(execution_time_ms);
    paramIndex++;
  }

  if (gpu_used !== undefined) {
    updates.push(`gpu_used = $${paramIndex}`);
    values.push(gpu_used);
    paramIndex++;
  }

  if (vram_used_mb !== undefined) {
    updates.push(`vram_used_mb = $${paramIndex}`);
    values.push(vram_used_mb);
    paramIndex++;
  }

  if (mode !== undefined) {
    updates.push(`mode = $${paramIndex}`);
    values.push(mode);
    paramIndex++;
  }

  if (batch_size !== undefined) {
    updates.push(`batch_size = $${paramIndex}`);
    values.push(batch_size);
    paramIndex++;
  }

  if (queue_wait_time_ms !== undefined) {
    updates.push(`queue_wait_time_ms = $${paramIndex}`);
    values.push(queue_wait_time_ms);
    paramIndex++;
  }

  if (result !== undefined) {
    updates.push(`result = $${paramIndex}`);
    values.push(JSON.stringify(result));
    paramIndex++;
  }

  if (updates.length === 0) return null;

  values.push(id);

  const query = `
    UPDATE gpu_queue_jobs
    SET ${updates.join(', ')}
    WHERE id = $${paramIndex}
    RETURNING *
  `;

  const dbResult = await pool.query(query, values);
  return dbResult.rows[0];
}

// Update job result (for storing job output)
export async function updateJobResult(id, result) {
  const query = `
    UPDATE gpu_queue_jobs
    SET result = $1
    WHERE id = $2
    RETURNING *
  `;
  
  const dbResult = await pool.query(query, [result, id]);
  return dbResult.rows[0];
}

// Update job metadata (for embedding-specific fields)
export async function updateJobMetadata(id, metadata) {
  const {
    embedding_dimensions,
    embedding_model,
    text_count,
    processing_time_ms,
    gpu_used
  } = metadata;

  const updates = [];
  const values = [];
  let paramIndex = 1;

  if (embedding_dimensions !== undefined) {
    updates.push(`embedding_dimensions = $${paramIndex}`);
    values.push(embedding_dimensions);
    paramIndex++;
  }

  if (embedding_model !== undefined) {
    updates.push(`embedding_model = $${paramIndex}`);
    values.push(embedding_model);
    paramIndex++;
  }

  if (text_count !== undefined) {
    updates.push(`text_count = $${paramIndex}`);
    values.push(text_count);
    paramIndex++;
  }

  if (processing_time_ms !== undefined) {
    updates.push(`execution_time_ms = $${paramIndex}`);
    values.push(processing_time_ms);
    paramIndex++;
  }

  if (gpu_used !== undefined) {
    updates.push(`gpu_used = $${paramIndex}`);
    values.push(gpu_used);
    paramIndex++;
  }

  if (updates.length === 0) return null;

  values.push(id);

  const query = `
    UPDATE gpu_queue_jobs
    SET ${updates.join(', ')}
    WHERE id = $${paramIndex}
    RETURNING *
  `;

  const dbResult = await pool.query(query, values);
  return dbResult.rows[0];
}

// Get queue status summary
export async function getQueueStatus() {
  const result = await pool.query(`
    SELECT
      status,
      COUNT(*) as count
    FROM gpu_queue_jobs
    GROUP BY status
  `);

  const statusCounts = { pending: 0, running: 0, completed: 0, failed: 0, cancelled: 0 };
  result.rows.forEach(row => {
    statusCounts[row.status] = parseInt(row.count);
  });

  return statusCounts;
}

// Get running job (if any)
export async function getRunningJob() {
  const result = await pool.query(
    "SELECT * FROM gpu_queue_jobs WHERE status = 'running' LIMIT 1"
  );
  return result.rows[0] || null;
}

// Cancel a job
export async function cancelJob(id) {
  return updateJobStatus(id, 'cancelled');
}

// Clean up old completed jobs (older than 24 hours)
export async function cleanupOldJobs() {
  const result = await pool.query(`
    DELETE FROM gpu_queue_jobs
    WHERE status IN ('completed', 'failed', 'cancelled')
    AND completed_at < NOW() - INTERVAL '24 hours'
    RETURNING id
  `);
  return result.rows.length;
}

// Get job type breakdown by status
export async function getJobTypeBreakdown() {
  const result = await pool.query(`
    SELECT
      type,
      status,
      COUNT(*) as count
    FROM gpu_queue_jobs
    GROUP BY type, status
    ORDER BY type, status
  `);

  const breakdown = {};
  result.rows.forEach(row => {
    if (!breakdown[row.type]) {
      breakdown[row.type] = {};
    }
    breakdown[row.type][row.status] = parseInt(row.count);
  });

  return breakdown;
}

// Get recent job history (last 5 jobs)
export async function getRecentJobs(limit = 5) {
  const result = await pool.query(
    `SELECT id, type, status, created_at, started_at, completed_at, error
     FROM gpu_queue_jobs
     WHERE status IN ('completed', 'failed', 'cancelled')
     ORDER BY completed_at DESC
     LIMIT $1`,
    [limit]
  );
  return result.rows;
}

// Get priority distribution for pending jobs
export async function getPriorityDistribution() {
  const result = await pool.query(`
    SELECT
      priority,
      COUNT(*) as count
    FROM gpu_queue_jobs
    WHERE status = 'pending'
    GROUP BY priority
    ORDER BY priority DESC
  `);

  const distribution = {};
  result.rows.forEach(row => {
    distribution[row.priority] = parseInt(row.count);
  });

  return distribution;
}

// Close pool on shutdown
export async function closePool() {
  await pool.end();
}

// Export pool for direct access (monitoring, etc.)
export { pool };

// Analytics functions for data collection

// Get performance metrics by job type
export async function getPerformanceMetricsByType(type = null, limit = 100) {
  let query = `
    SELECT 
      type,
      mode,
      AVG(execution_time_ms) as avg_execution_time,
      MIN(execution_time_ms) as min_execution_time,
      MAX(execution_time_ms) as max_execution_time,
      AVG(vram_used_mb) as avg_vram_used,
      COUNT(*) as job_count,
      AVG(queue_wait_time_ms) as avg_queue_wait
    FROM gpu_queue_jobs
    WHERE execution_time_ms IS NOT NULL
  `;
  const params = [];
  let paramIndex = 1;

  if (type) {
    query += ` AND type = $${paramIndex}`;
    params.push(type);
    paramIndex++;
  }

  query += ` GROUP BY type, mode ORDER BY type, mode`;

  if (limit) {
    query += ` LIMIT $${paramIndex}`;
    params.push(limit);
    paramIndex++;
  }

  const result = await pool.query(query, params);
  return result.rows;
}

// Get comparative metrics (CPU vs GPU)
export async function getComparativeMetrics() {
  const result = await pool.query(`
    SELECT 
      type,
      mode,
      COUNT(*) as job_count,
      AVG(execution_time_ms) as avg_time,
      STDDEV(execution_time_ms) as std_dev_time,
      AVG(vram_used_mb) as avg_vram,
      AVG(queue_wait_time_ms) as avg_wait
    FROM gpu_queue_jobs
    WHERE execution_time_ms IS NOT NULL
      AND mode IS NOT NULL
    GROUP BY type, mode
    ORDER BY type, mode
  `);
  return result.rows;
}

// Get queue efficiency metrics
export async function getQueueEfficiencyMetrics() {
  const result = await pool.query(`
    SELECT 
      DATE(created_at) as date,
      type,
      COUNT(*) as total_jobs,
      SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed_jobs,
      SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed_jobs,
      AVG(execution_time_ms) as avg_execution_time,
      AVG(queue_wait_time_ms) as avg_queue_wait,
      AVG(CASE WHEN status = 'completed' THEN 
        EXTRACT(EPOCH FROM (completed_at - started_at)) * 1000 
      END) as avg_total_time
    FROM gpu_queue_jobs
    WHERE created_at > NOW() - INTERVAL '7 days'
    GROUP BY DATE(created_at), type
    ORDER BY date DESC, type
  `);
  return result.rows;
}

// Get VRAM usage patterns
export async function getVRAMUsagePatterns() {
  const result = await pool.query(`
    SELECT 
      type,
      mode,
      AVG(vram_used_mb) as avg_vram,
      MIN(vram_used_mb) as min_vram,
      MAX(vram_used_mb) as max_vram,
      PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY vram_used_mb) as median_vram,
      COUNT(*) as sample_count
    FROM gpu_queue_jobs
    WHERE vram_used_mb IS NOT NULL
    GROUP BY type, mode
    ORDER BY type, mode
  `);
  return result.rows;
}

// Get recent job history with metrics
export async function getRecentJobsWithMetrics(limit = 50) {
  const result = await pool.query(`
    SELECT 
      id,
      type,
      status,
      mode,
      priority,
      execution_time_ms,
      gpu_used,
      vram_used_mb,
      queue_wait_time_ms,
      batch_size,
      created_at,
      started_at,
      completed_at,
      error
    FROM gpu_queue_jobs
    ORDER BY created_at DESC
    LIMIT $1
  `, [limit]);
  return result.rows;
}

// Get job statistics for monitoring
export async function getJobStats(hours = 24) {
  const query = `
    SELECT 
      type,
      status,
      COUNT(*) as count,
      AVG(execution_time_ms) as avg_execution_time_ms,
      AVG(queue_wait_time_ms) as avg_queue_wait_time_ms,
      AVG(retry_count) as avg_retry_count
    FROM gpu_queue_jobs
    WHERE created_at > NOW() - INTERVAL '${hours} hours'
    GROUP BY type, status
    ORDER BY type, status
  `;
  
  const result = await pool.query(query);
  return result.rows;
}

// Get cancellation rate for monitoring
export async function getCancellationRate(hours = 24) {
  const query = `
    SELECT 
      type,
      COUNT(*) FILTER (WHERE status = 'cancelled') as cancelled,
      COUNT(*) FILTER (WHERE status = 'completed') as completed,
      COUNT(*) FILTER (WHERE status = 'failed') as failed,
      COUNT(*) as total,
      ROUND(COUNT(*) FILTER (WHERE status = 'cancelled')::numeric / COUNT(*) * 100, 2) as cancellation_rate
    FROM gpu_queue_jobs
    WHERE created_at > NOW() - INTERVAL '${hours} hours'
    GROUP BY type
    ORDER BY type
  `;
  
  const result = await pool.query(query);
  return result.rows;
}

// Get recent job failures for analysis
export async function getRecentFailures(limit = 10) {
  const query = `
    SELECT id, type, status, error, created_at, started_at, completed_at, retry_count
    FROM gpu_queue_jobs
    WHERE status IN ('failed', 'cancelled')
    ORDER BY created_at DESC
    LIMIT $1
  `;
  
  const result = await pool.query(query, [limit]);
  return result.rows;
}

