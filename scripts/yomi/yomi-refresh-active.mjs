const API = 'http://127.0.0.1:3000';
const MAX_ACTIVE = 20;

async function getConversations() {
  const res = await fetch(`${API}/api/yomi/conversations`);
  if (!res.ok) throw new Error(`conversations ${res.status}: ${await res.text()}`);
  const data = await res.json();
  return Array.isArray(data?.conversations) ? data.conversations : [];
}

async function refreshChat(chatId) {
  const res = await fetch(`${API}/api/yomi/refresh?chat=${encodeURIComponent(chatId)}`, { method: 'POST' });
  if (!res.ok) throw new Error(`refresh ${chatId} ${res.status}: ${await res.text()}`);
  const body = await res.json();
  if (!body.ok) throw new Error(`refresh ${chatId} failed: ${JSON.stringify(body)}`);
}

function isActive(c) {
  const unread = Number(c.unread) || 0;
  if (unread > 0) return true;
  const ts = Number(c.lastMessageTime) || 0;
  return ts > Date.now() - 60 * 60 * 1000;
}

async function main() {
  const all = await getConversations();
  const active = all
    .filter(isActive)
    .sort((a, b) => (b.unread || 0) - (a.unread || 0) || (b.lastMessageTime || 0) - (a.lastMessageTime || 0))
    .slice(0, MAX_ACTIVE);

  if (active.length === 0) {
    console.log('No active Yomi chats to refresh');
    return;
  }

  console.log(`Refreshing ${active.length} active Yomi chat(s)`);
  for (const c of active) {
    console.log(`- ${c.id} (${c.name || 'unnamed'}, unread=${c.unread || 0})`);
    await refreshChat(c.id);
  }
  console.log('Active refresh done');
}

main().catch(err => {
  console.error('yomi-refresh-active failed:', err);
  process.exit(1);
});
