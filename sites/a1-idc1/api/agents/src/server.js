import path from 'path';
import fs from 'fs';
import { promises as fsp } from 'fs';
import express from 'express';
import morgan from 'morgan';
import dotenv from 'dotenv';
import { fileURLToPath } from 'url';
import { nanoid } from 'nanoid';

dotenv.config();

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const app = express();
const PORT = process.env.PORT || 4060;

app.use(morgan('dev'));
app.use(express.json({ limit: '2mb' }));

const repoRoot = path.join(__dirname, '..', '..', '..', '..', '..');
const candidateDataRoots = [
  process.env.AGENTS_DATA_ROOT,
  path.join(repoRoot, 'mcp', 'mcp-agents', 'data', 'agents'),
  path.join(__dirname, '..', '..', '..', 'data', 'agents')
].filter(Boolean);

let dataRoot =
  candidateDataRoots.find((dir) => {
    try {
      return fs.existsSync(dir);
    } catch {
      return false;
    }
  }) ||
  candidateDataRoots[0] ||
  path.join(repoRoot, 'mcp', 'mcp-agents', 'data', 'agents');

fs.mkdirSync(dataRoot, { recursive: true });
const usersDir = path.join(dataRoot, 'users');
fs.mkdirSync(usersDir, { recursive: true });
const spaCandidates = [
  path.join(repoRoot, 'mcp', 'mcp-agents', 'www', 'test', 'agens'),
  path.join(__dirname, '..', '..', 'www', 'test', 'agents'),
  path.join(__dirname, '..', '..', 'test', 'agents')
];
const agentsSpaRoot = spaCandidates.find((dir) => fs.existsSync(dir)) || spaCandidates[spaCandidates.length - 1];
const agentsSpaIndex = path.join(agentsSpaRoot, 'index.html');

const userCache = new Map();
const sseClients = new Map(); // sessionId -> Set(res)
const sessionRuntime = new Map(); // sessionId -> { eventHistory: [] }
const activeRuns = new Map(); // runId -> metadata

const defaultUserData = (userId) => ({
  userId,
  sessions: [],
  archives: [],
  attachments: []
});

const getUserFile = (userId) => path.join(usersDir, `${userId}.json`);

const loadUserData = async (userId) => {
  if (userCache.has(userId)) {
    return userCache.get(userId);
  }
  const file = getUserFile(userId);
  try {
    const contents = await fsp.readFile(file, 'utf8');
    const parsed = JSON.parse(contents);
    userCache.set(userId, parsed);
    return parsed;
  } catch (error) {
    const data = defaultUserData(userId);
    userCache.set(userId, data);
    return data;
  }
};

const saveUserData = async (userId) => {
  const data = userCache.get(userId) || defaultUserData(userId);
  await fsp.writeFile(getUserFile(userId), JSON.stringify(data, null, 2), 'utf8');
};

const findSession = (data, sessionId) => data.sessions.find((session) => session.id === sessionId);
const findArchive = (data, archiveId) => data.archives.find((archive) => archive.archiveId === archiveId);

const ensureRuntime = (sessionId) => {
  if (!sessionRuntime.has(sessionId)) {
    sessionRuntime.set(sessionId, { eventHistory: [] });
  }
  return sessionRuntime.get(sessionId);
};

const broadcastEvent = (sessionId, eventName, payload) => {
  const runtime = ensureRuntime(sessionId);
  runtime.eventHistory.push({ event: eventName, payload, timestamp: new Date().toISOString() });
  runtime.eventHistory = runtime.eventHistory.slice(-50);

  const clients = sseClients.get(sessionId);
  if (!clients || !clients.size) {
    return;
  }

  const serialized = JSON.stringify(payload || {});
  clients.forEach((client) => {
    client.write(`event: ${eventName}\n`);
    client.write(`data: ${serialized}\n\n`);
  });
};

const normalizeLimit = (value, fallback = 20) => {
  const num = Number(value);
  if (Number.isNaN(num) || num <= 0) {
    return fallback;
  }
  return Math.min(num, 100);
};

const summarizeSession = (session, prompt) => {
  if (prompt) {
    return prompt.slice(0, 120);
  }
  const lastAssistant = [...(session.messages || [])].reverse().find((msg) => msg.role === 'assistant');
  return lastAssistant?.content?.slice(0, 120) || session.metadata?.title || `Session ${session.id.slice(0, 6)}`;
};

const markSessionRunning = async (userId, sessionId, status) => {
  const data = await loadUserData(userId);
  const session = findSession(data, sessionId);
  if (!session) return;
  session.status = status;
  session.updatedAt = new Date().toISOString();
  await saveUserData(userId);
};

const enqueueSimulatedRun = async ({ userId, session, runId, agents, prompt }) => {
  const phases = agents.length ? agents : ['orchestrator'];
  activeRuns.set(runId, {
    userId,
    sessionId: session.id,
    status: 'running',
    startedAt: Date.now(),
    agents: phases
  });

  broadcastEvent(session.id, 'run_status', { runId, status: 'running' });

  phases.forEach((agent, index) => {
    const startDelay = 600 + index * 1200;
    const finishDelay = startDelay + 900;

    setTimeout(() => {
      broadcastEvent(session.id, 'agent_update', {
        runId,
        agent,
        status: 'running',
        content: `(${agent}) is analyzing "${prompt.slice(0, 35)}…"`,
        timestamp: new Date().toISOString()
      });
    }, startDelay);

    setTimeout(async () => {
      const data = await loadUserData(userId);
      const liveSession = findSession(data, session.id);
      if (!liveSession) return;
      const content = `${agent} finished their step for: ${prompt.slice(0, 40)}…`;
      liveSession.messages = liveSession.messages || [];
      liveSession.messages.push({
        id: nanoid(10),
        role: 'assistant',
        agent,
        content,
        timestamp: new Date().toISOString()
      });
      liveSession.messageCount = liveSession.messages.length;
      liveSession.updatedAt = new Date().toISOString();
      liveSession.agents = Array.from(new Set([...(liveSession.agents || []), agent]));
      if (!liveSession.metadata?.title || liveSession.metadata.autoTitle) {
        liveSession.metadata = liveSession.metadata || {};
        liveSession.metadata.title = prompt.slice(0, 40) || `Session ${session.id.slice(0, 6)}`;
      }
      await saveUserData(userId);

      broadcastEvent(session.id, 'agent_update', {
        runId,
        agent,
        status: 'done',
        content,
        timestamp: new Date().toISOString()
      });

      if (index === phases.length - 1) {
        await markSessionRunning(userId, session.id, 'idle');
        activeRuns.set(runId, { ...activeRuns.get(runId), status: 'done' });
        broadcastEvent(session.id, 'run_complete', {
          runId,
          status: 'done',
          summary: summarizeSession(liveSession, prompt),
          timestamp: new Date().toISOString()
        });
      }
    }, finishDelay);
  });
};

app.get('/api/users/:userId/sessions', async (req, res) => {
  const { userId } = req.params;
  const { limit = 20, status } = req.query;
  const data = await loadUserData(userId);
  let sessions = data.sessions || [];
  if (status) {
    sessions = sessions.filter((session) => session.status === status);
  }
  sessions = sessions
    .slice()
    .sort((a, b) => new Date(b.updatedAt) - new Date(a.updatedAt))
    .slice(0, normalizeLimit(limit));
  res.json({ sessions });
});

app.post('/api/users/:userId/sessions', async (req, res) => {
  const { userId } = req.params;
  const data = await loadUserData(userId);
  const id = nanoid(12);
  const now = new Date().toISOString();
  const session = {
    id,
    userId,
    createdAt: now,
    updatedAt: now,
    status: 'idle',
    messageCount: 0,
    agents: ['orchestrator'],
    metadata: {
      title: req.body?.metadata?.title || `Session ${id.slice(0, 6)}`,
      pinned: false,
      autoTitle: req.body?.metadata?.autoTitle ?? true
    },
    messages: []
  };
  data.sessions.push(session);
  await saveUserData(userId);
  res.status(201).json({ session });
});

app.patch('/api/users/:userId/sessions/:sessionId', async (req, res) => {
  const { userId, sessionId } = req.params;
  const data = await loadUserData(userId);
  const session = findSession(data, sessionId);
  if (!session) {
    return res.status(404).json({ error: 'session_not_found' });
  }
  const { metadata } = req.body || {};
  if (metadata) {
    session.metadata = {
      ...session.metadata,
      ...metadata
    };
  }
  session.updatedAt = new Date().toISOString();
  await saveUserData(userId);
  res.json({ session });
});

app.delete('/api/users/:userId/sessions/:sessionId', async (req, res) => {
  const { userId, sessionId } = req.params;
  const { reason } = req.body || {};
  const data = await loadUserData(userId);
  const sessionIndex = data.sessions.findIndex((session) => session.id === sessionId);
  if (sessionIndex === -1) {
    return res.status(404).json({ error: 'session_not_found' });
  }
  const session = data.sessions[sessionIndex];
  data.sessions.splice(sessionIndex, 1);

  const archiveId = nanoid(10);
  const archive = {
    archiveId,
    sessionId,
    summary: reason || summarizeSession(session),
    deletedAt: new Date().toISOString(),
    agents: session.agents,
    messageCount: session.messageCount,
    storedMessages: (session.messages || []).slice(-20)
  };
  data.archives.push(archive);
  await saveUserData(userId);
  res.json({ archiveId, archivePath: `/api/users/${userId}/archives/${archiveId}` });
});

app.get('/api/users/:userId/archives', async (req, res) => {
  const { userId } = req.params;
  const { limit = 20 } = req.query;
  const data = await loadUserData(userId);
  const archives = (data.archives || [])
    .slice()
    .sort((a, b) => new Date(b.deletedAt) - new Date(a.deletedAt))
    .slice(0, normalizeLimit(limit));
  res.json({ archives });
});

app.get('/api/users/:userId/archives/:archiveId', async (req, res) => {
  const { userId, archiveId } = req.params;
  const data = await loadUserData(userId);
  const archive = findArchive(data, archiveId);
  if (!archive) {
    return res.status(404).json({ error: 'archive_not_found' });
  }
  res.json({ archive });
});

app.post('/api/users/:userId/sessions/:sessionId/attachments', async (req, res) => {
  const { userId, sessionId } = req.params;
  const { name, size, mime } = req.body || {};
  if (!name) {
    return res.status(400).json({ error: 'attachment_name_required' });
  }
  const data = await loadUserData(userId);
  const session = findSession(data, sessionId);
  if (!session) {
    return res.status(404).json({ error: 'session_not_found' });
  }
  const attachment = {
    id: nanoid(12),
    name,
    size: Number(size) || 0,
    mime: mime || 'application/octet-stream',
    createdAt: new Date().toISOString()
  };
  data.attachments.push(attachment);
  await saveUserData(userId);
  res.status(201).json({ attachment });
});

app.post('/api/users/:userId/sessions/:sessionId/messages', async (req, res) => {
  const { userId, sessionId } = req.params;
  const { prompt, agents = [], historyLimit = 20, attachments = [], locale = 'en-US', metadata = {} } = req.body || {};

  if (!prompt || typeof prompt !== 'string') {
    return res.status(400).json({ error: 'prompt_required' });
  }

  const data = await loadUserData(userId);
  let session = findSession(data, sessionId);

  if (!session) {
    session = {
      id: sessionId || nanoid(12),
      userId,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
      status: 'idle',
      messageCount: 0,
      agents: [],
      metadata: { title: `Session ${sessionId.slice(0, 6)}`, pinned: false, autoTitle: true },
      messages: []
    };
    data.sessions.push(session);
  }

  session.messages = session.messages || [];
  session.messages.push({
    id: nanoid(10),
    role: 'user',
    content: prompt,
    attachments,
    locale,
    timestamp: new Date().toISOString()
  });
  if (session.messages.length > historyLimit) {
    session.messages = session.messages.slice(-historyLimit);
  }
  session.messageCount = session.messages.length;
  session.updatedAt = new Date().toISOString();
  session.status = 'running';
  await saveUserData(userId);

  const runId = nanoid(14);
  res.json({
    sessionId: session.id,
    runId,
    status: 'accepted',
    queuedAgents: agents
  });

  await enqueueSimulatedRun({ userId, session, runId, agents, prompt, metadata });
});

app.get('/api/users/:userId/sessions/:sessionId/stream', async (req, res) => {
  const { sessionId } = req.params;
  res.setHeader('Content-Type', 'text/event-stream');
  res.setHeader('Cache-Control', 'no-store');
  res.setHeader('Connection', 'keep-alive');
  res.flushHeaders?.();

  const clients = sseClients.get(sessionId) || new Set();
  clients.add(res);
  sseClients.set(sessionId, clients);

  const runtime = ensureRuntime(sessionId);
  runtime.eventHistory.forEach((entry) => {
    res.write(`event: ${entry.event}\n`);
    res.write(`data: ${JSON.stringify(entry.payload)}\n\n`);
  });

  const heartbeat = setInterval(() => {
    if (res.writableEnded) {
      clearInterval(heartbeat);
      return;
    }
    res.write('event: heartbeat\n');
    res.write('data: {}\n\n');
  }, 30000);

  req.on('close', () => {
    clearInterval(heartbeat);
    clients.delete(res);
    if (!clients.size) {
      sseClients.delete(sessionId);
    }
  });
});

app.get('/api/agents/registry', (_req, res) => {
  const registry = path.join(__dirname, '..', '..', '..', 'site-man', 'agents', 'registry.json');
  res.sendFile(registry);
});

app.get('/api/health', async (_req, res) => {
  const files = await fsp.readdir(usersDir);
  res.json({
    status: 'ok',
    usersTracked: files.length,
    timestamp: new Date().toISOString()
  });
});

if (fs.existsSync(agentsSpaRoot)) {
  const spaMounts = ['/www/test/agens', '/www/test/agents'];
  spaMounts.forEach((mountPath) => {
    app.use(mountPath, express.static(agentsSpaRoot, { index: false, fallthrough: true }));
    app.get([mountPath, `${mountPath}/*`], (_req, res, next) => {
      if (fs.existsSync(agentsSpaIndex)) {
        return res.sendFile(agentsSpaIndex);
      }
      return next();
    });
  });
}

app.listen(PORT, () => {
  console.log(`[agents-api] listening on port ${PORT}`);
});
