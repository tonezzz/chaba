/**
 * Migration script to add media_analysis_jobs table
 * This enables tracking of media analysis jobs for cost analysis and debugging
 */

import pg from 'pg';
const { Pool } = pg;

const user = process.env.POSTGRES_USER || 'chaba';
const password = process.env.POSTGRES_PASSWORD || 'chabapass';
const db = process.env.POSTGRES_DB || 'chaba';
const host = process.env.POSTGRES_HOST || '127.0.0.1';
const port = process.env.POSTGRES_PORT || '5432';

const pool = new Pool({
  connectionString: process.env.DATABASE_URL
    || `postgres://${user}:${password}@${host}:${port}/${db}`,
});

async function migrate() {
  const client = await pool.connect();
  try {
    await client.query(`
      CREATE TABLE IF NOT EXISTS media_analysis_jobs (
        id SERIAL PRIMARY KEY,
        chat_id TEXT NOT NULL REFERENCES conversations(chat_id) ON DELETE CASCADE,
        message_id TEXT NOT NULL REFERENCES messages(message_id) ON DELETE CASCADE,
        media_type TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        analysis_result TEXT,
        model_used TEXT,
        started_at TIMESTAMPTZ,
        completed_at TIMESTAMPTZ,
        error_message TEXT,
        tokens_used INTEGER,
        cost_usd NUMERIC(10, 6),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
      );
    `);

    await client.query(`
      CREATE INDEX IF NOT EXISTS media_analysis_jobs_chat_id ON media_analysis_jobs(chat_id);
    `);

    await client.query(`
      CREATE INDEX IF NOT EXISTS media_analysis_jobs_status ON media_analysis_jobs(status);
    `);

    await client.query(`
      CREATE INDEX IF NOT EXISTS media_analysis_jobs_created_at ON media_analysis_jobs(created_at DESC);
    `);

    console.log('Migration completed successfully: media_analysis_jobs table created');
  } catch (error) {
    console.error('Migration failed:', error);
    throw error;
  } finally {
    client.release();
    await pool.end();
  }
}

migrate().catch(console.error);