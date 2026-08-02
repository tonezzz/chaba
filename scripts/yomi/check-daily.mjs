import pool from './db.mjs';

async function check() {
  const chatId = 'cc8589a45e890e38942825d3c13ec3439';
  const { rows } = await pool.query(`
    SELECT date, events, actions, topics, message_count, updated_at
    FROM daily_summaries
    WHERE chat_id = $1
    ORDER BY date DESC
  `, [chatId]);
  console.log('Daily summaries for', chatId);
  console.log(JSON.stringify(rows, null, 2));
  await pool.end();
}

check().catch(err => {
  console.error(err);
  process.exit(1);
});
