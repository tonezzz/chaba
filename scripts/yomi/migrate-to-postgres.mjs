import { readdirSync, readFileSync, existsSync } from 'node:fs';
import pool from './db.mjs';

const JSON_DIR = '/home/tony/CascadeProjects/chaba-tony-dell/stacks/web/public/apps/yomi';

async function saveMessages(chatId, messages) {
  if (!messages.length) return;
  const ids = messages.map(m => m.id);
  const chatIds = Array(messages.length).fill(chatId);
  const fromNames = messages.map(m => m.fromName || null);
  const deliveredTimes = messages.map(m => m.deliveredTime || null);
  const texts = messages.map(m => m.text || null);
  const mediaTypes = messages.map(m => m.mediaType || null);
  const mediaPaths = messages.map(m => m.mediaFile || null);
  const e2ees = messages.map(m => JSON.stringify(m.e2ee ?? null));
  const datas = messages.map(m => JSON.stringify(m));
  await pool.query(`
    INSERT INTO messages (message_id, chat_id, from_name, delivered_time, text, media_type, media_path, e2ee, data)
    SELECT * FROM unnest($1::text[], $2::text[], $3::text[], $4::bigint[], $5::text[], $6::text[], $7::text[], $8::jsonb[], $9::jsonb[])
    ON CONFLICT (message_id) DO UPDATE SET
      chat_id = EXCLUDED.chat_id,
      from_name = EXCLUDED.from_name,
      delivered_time = EXCLUDED.delivered_time,
      text = EXCLUDED.text,
      media_type = EXCLUDED.media_type,
      media_path = EXCLUDED.media_path,
      e2ee = EXCLUDED.e2ee,
      data = EXCLUDED.data
  `, [ids, chatIds, fromNames, deliveredTimes, texts, mediaTypes, mediaPaths, e2ees, datas]);
}

async function saveConversation(conv) {
  await pool.query(`
    INSERT INTO conversations (chat_id, name, is_group, category, category_source, unread, last_message_time, last_preview, summary, meta)
    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
    ON CONFLICT (chat_id) DO UPDATE SET
      name = EXCLUDED.name,
      is_group = EXCLUDED.is_group,
      category = EXCLUDED.category,
      category_source = EXCLUDED.category_source,
      unread = EXCLUDED.unread,
      last_message_time = EXCLUDED.last_message_time,
      last_preview = EXCLUDED.last_preview,
      summary = EXCLUDED.summary,
      meta = EXCLUDED.meta,
      updated_at = NOW()
  `, [conv.id, conv.name, conv.isGroup, conv.category, conv.categorySource, conv.unread, conv.lastMessageTime, conv.lastPreview, conv.summary, JSON.stringify({})]);
}

async function main() {
  const convPath = `${JSON_DIR}/conversations.json`;
  if (!existsSync(convPath)) {
    console.log('No conversations.json found, nothing to migrate.');
    return;
  }
  const { conversations = [] } = JSON.parse(readFileSync(convPath, 'utf8'));
  const messagesDir = `${JSON_DIR}/messages`;

  let msgFiles = 0;
  let msgRows = 0;
  for (const conv of conversations) {
    await saveConversation(conv);
    const p = `${messagesDir}/${conv.id}.json`;
    if (existsSync(p)) {
      const { messages = [] } = JSON.parse(readFileSync(p, 'utf8'));
      const valid = messages.filter(m => m.id);
      await saveMessages(conv.id, valid);
      msgFiles++;
      msgRows += valid.length;
    }
  }

  console.log(`Migrated ${conversations.length} conversations and ${msgRows} messages from ${msgFiles} files.`);
  await pool.end();
}

main().catch(err => {
  console.error(err);
  pool.end();
  process.exit(1);
});
