import { randomUUID } from 'crypto';

const MAX_CHATS = Number(process.env.MCP_DEVOPS_MAX_CHATS || 50);

const clone = (value) => JSON.parse(JSON.stringify(value));

class ChatStore {
  constructor() {
    this.chats = new Map();
  }

  createChat({ message, clientId, dryRun }) {
    const id = randomUUID();
    const now = new Date().toISOString();
    const record = {
      id,
      client_id: clientId || null,
      status: 'planning',
      dry_run: Boolean(dryRun),
      created_at: now,
      updated_at: now,
      message: message || '',
      plan: null,
      approval_required: true,
      approved_at: null,
      execution: null,
      error: null
    };
    this.chats.set(id, record);
    this.#trim();
    return clone(record);
  }

  updateChat(id, patch) {
    const record = this.chats.get(id);
    if (!record) return null;
    const next = {
      ...record,
      ...patch,
      updated_at: new Date().toISOString()
    };
    this.chats.set(id, next);
    return clone(next);
  }

  getChat(id) {
    const record = this.chats.get(id);
    return record ? clone(record) : null;
  }

  listChats() {
    return Array.from(this.chats.values())
      .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
      .map((chat) => clone(chat));
  }

  #trim() {
    if (this.chats.size <= MAX_CHATS) return;
    const sorted = Array.from(this.chats.entries()).sort(
      (a, b) => new Date(a[1].created_at).getTime() - new Date(b[1].created_at).getTime()
    );
    while (sorted.length > MAX_CHATS) {
      const [id] = sorted.shift();
      this.chats.delete(id);
    }
  }
}

export const chatStore = new ChatStore();
