#!/usr/bin/env node
/**
 * digest-to-mddb.mjs — mirror Yomi LINE digests into MDDB's private
 * `yomi-digest` collection (NOT registered as an Ada memory bank: reachable
 * via MDDB search from devin/console sessions, invisible to Ada voice recall).
 *
 * Source of truth: Postgres `daily_summaries` (Gemini-distilled per chat+date:
 * events/actions/topics + summary text) joined to `conversations` for names,
 * plus media_analysis snippets for that day. Key: line/<chat-slug>/<date> —
 * /v1/add upserts by key, so re-mirroring a window is idempotent.
 *
 * Runs inside the same podman node image/env as update-conversations.mjs.
 * Env: DIGEST_DAYS (default 2), MDDB_URL (default http://100.74.146.0:11023).
 */
import pool from './db.mjs';

const MDDB = (process.env.MDDB_URL || 'http://100.74.146.0:11023').replace(/\/+$/, '');
const COLLECTION = process.env.DIGEST_COLLECTION || 'yomi-digest';
const DAYS = parseInt(process.env.DIGEST_DAYS || '2', 10);

const slug = (s) => (s || 'unknown').toLowerCase()
  .replace(/[^a-z0-9ก-๙]+/gi, '-').replace(/^-+|-+$/g, '').slice(0, 48) || 'unknown';

async function mddbAdd(doc) {
  const r = await fetch(`${MDDB}/v1/add`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(doc),
  });
  if (!r.ok) throw new Error(`mddb add ${r.status}: ${await r.text()}`);
}

const { rows: sums } = await pool.query(
  `SELECT s.chat_id, s.date, s.events, s.actions, s.topics, s.summary,
          s.message_count, c.name AS chat_name, c.is_group
     FROM daily_summaries s
     JOIN conversations c ON c.chat_id = s.chat_id
    WHERE s.date >= CURRENT_DATE - $1::int
    ORDER BY s.date DESC, s.updated_at DESC`, [DAYS]);

let written = 0, failed = 0;
for (const s of sums) {
  const date = s.date instanceof Date ? s.date.toISOString().slice(0, 10) : String(s.date).slice(0, 10);
  const chat = s.chat_name || s.chat_id;

  const { rows: media } = await pool.query(
    `SELECT from_name, media_type, media_analysis
       FROM messages
      WHERE chat_id = $1
        AND to_timestamp(delivered_time / 1000)::date = $2::date
        AND media_analysis IS NOT NULL
      ORDER BY delivered_time DESC LIMIT 5`, [s.chat_id, date]);

  const list = (a) => (Array.isArray(a) ? a : []).map((x) => `- ${x}`).join('\n');
  const contentMd = [
    `**${chat}** — ${date} — ${s.message_count} messages`,
    '',
    s.summary || '(no summary)',
    s.events?.length ? `\nEvents:\n${list(s.events)}` : '',
    s.actions?.length ? `\nActions/requests:\n${list(s.actions)}` : '',
    s.topics?.length ? `\nTopics: ${(s.topics || []).join(', ')}` : '',
    media.length
      ? `\nMedia:\n${media.map((m) => `- ${m.from_name || '?'} [${m.media_type}]: ${m.media_analysis}`).join('\n')}`
      : '',
  ].filter(Boolean).join('\n');

  try {
    await mddbAdd({
      collection: COLLECTION,
      key: `line/${slug(chat)}/${date}`,
      lang: 'th',  // mostly Thai; harmless if wrong — MDDB treats as hint
      contentMd,
      meta: {
        kind: ['message-digest'],
        source: ['yomi'],
        chat: [chat],
        chat_id: [s.chat_id],
        date: [date],
        is_group: [String(!!s.is_group)],
        message_count: [String(s.message_count)],
        scope: ['tony'],
        written_by: ['yomi-digest'],
        status: ['active'],
      },
    });
    written++;
  } catch (e) {
    failed++;
    console.error(`digest ${chat} ${date}: ${e.message}`);
  }
}
console.log(`digests: ${written} written, ${failed} failed, window ${DAYS}d -> ${COLLECTION}`);
await pool.end();
process.exit(failed && !written ? 1 : 0);
