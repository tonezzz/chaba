import pool from './db.mjs';

async function migrate() {
  const client = await pool.connect();
  try {
    await client.query(`
      CREATE TABLE IF NOT EXISTS daily_summaries (
        id SERIAL PRIMARY KEY,
        chat_id TEXT NOT NULL REFERENCES conversations(chat_id) ON DELETE CASCADE,
        date DATE NOT NULL,
        events TEXT[],
        actions TEXT[],
        topics TEXT[],
        summary TEXT,
        message_count INTEGER NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(chat_id, date)
      )
    `);
    console.log('Created daily_summaries table');

    await client.query(`
      CREATE INDEX IF NOT EXISTS daily_summaries_chat_date 
      ON daily_summaries(chat_id, date DESC)
    `);
    console.log('Created daily_summaries_chat_date index');
  } finally {
    client.release();
  }
  await pool.end();
}

migrate().catch(err => {
  console.error('Migration failed:', err);
  process.exit(1);
});
