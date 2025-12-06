import path from 'path';
import express from 'express';
import morgan from 'morgan';
import { fileURLToPath } from 'url';
import dotenv from 'dotenv';
import { nanoid } from 'nanoid';

dotenv.config();

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const app = express();
const PORT = process.env.PORT || 4060;

app.use(morgan('dev'));
app.use(express.json());

const users = new Map();

const ensureUser = (userId) => {
  if (!users.has(userId)) {
    users.set(userId, {
      sessions: new Map(),
      archives: new Map()
    });
  }
  return users.get(userId);
};

app.get('/api/users/:userId/sessions', (req, res) => {
  const { userId } = req.params;
  const { limit = 20 } = req.query;
  const store = ensureUser(userId);
  const sessions = Array.from(store.sessions.values())
    .sort((a, b) => new Date(b.updatedAt) - new Date(a.updatedAt))
    .slice(0, Number(limit) || 20);
  res.json({ sessions });
});

app.post('/api/users/:userId/sessions', (req, res) => {
  const { userId } = req.params;
  const store = ensureUser(userId);
  const id = nanoid(12);
  const session = {
    id,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    messageCount: 0,
    agents: ['orchestrator'],
    metadata: { title: `Session ${id.slice(0, 6)}` }
  };
  store.sessions.set(id, session);
  res.status(201).json({ session });
});

app.delete('/api/users/:userId/sessions/:sessionId', (req, res) => {
  const { userId, sessionId } = req.params;
  const store = ensureUser(userId);
  const session = store.sessions.get(sessionId);
  if (!session) {
    return res.status(404).json({ error: 'session_not_found' });
  }
  store.sessions.delete(sessionId);
  const archiveId = nanoid(10);
  const archive = {
    archiveId,
    sessionId,
    summary: session.metadata?.title || `Session ${sessionId}`,
    deletedAt: new Date().toISOString(),
    agents: session.agents,
    messageCount: session.messageCount,
    storedMessages: []
  };
  store.archives.set(archiveId, archive);
  res.json({ archiveId });
});

app.get('/api/users/:userId/archives', (req, res) => {
  const { userId } = req.params;
  const { limit = 20 } = req.query;
  const store = ensureUser(userId);
  const archives = Array.from(store.archives.values())
    .sort((a, b) => new Date(b.deletedAt) - new Date(a.deletedAt))
    .slice(0, Number(limit) || 20);
  res.json({ archives });
});

app.get('/api/users/:userId/archives/:archiveId', (req, res) => {
  const { userId, archiveId } = req.params;
  const store = ensureUser(userId);
  const archive = store.archives.get(archiveId);
  if (!archive) {
    return res.status(404).json({ error: 'archive_not_found' });
  }
  res.json({ archive });
});

app.get('/api/agents/registry', (_req, res) => {
  const registry = path.join(__dirname, '..', '..', '..', 'site-man', 'agents', 'registry.json');
  res.sendFile(registry);
});

app.get('/api/health', (_req, res) => {
  res.json({ status: 'ok', sessions: users.size, timestamp: new Date().toISOString() });
});

app.listen(PORT, () => {
  console.log(`[agents-api] listening on port ${PORT}`);
});
