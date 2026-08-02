import pg from 'pg';

const { Pool } = pg;

// Read DATABASE_URL from environment or use default
const DATABASE_URL = process.env.DATABASE_URL || 'postgres://chaba:chabapass@localhost:5432/chaba';

const pool = new Pool({
  connectionString: DATABASE_URL,
});

// Priority mapping
const PRIORITY = {
  txt2vid: 3,
  imagen2: 2,
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

// Get queue status summary
export async function getQueueStatus() {
  const result = await pool.query(`
    SELECT
      status,
      COUNT(*) as count
    FROM gpu_queue_jobs
    GROUP BY status
  `);

  const statusCounts = {};
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

// Close pool on shutdown
export async function closePool() {
  await pool.end();
}
