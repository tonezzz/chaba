import crypto from 'crypto';
import { spawn } from 'child_process';
import path from 'path';
import express from 'express';
import morgan from 'morgan';
import { fileURLToPath } from 'url';
import dotenv from 'dotenv';
import { promises as fs } from 'fs';

dotenv.config();

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const app = express();
const PORT = Number(process.env.PORT) || 3000;
const TALK_PORT = Number(process.env.TALK_PORT) || 3001;
const WEBHOOK_SECRET = (process.env.NODE1_WEBHOOK_SECRET || '').trim();
const TONY_DEPLOY_SECRET = (process.env.TONY_DEPLOY_SECRET || WEBHOOK_SECRET).trim();
const NODE_DOMAIN = (process.env.NODE_DOMAIN || 'node-1.h3.surf-thailand.com').trim();
const GLAMA_API_URL =
  (process.env.GLAMA_API_URL || process.env.GLAMA_URL || 'https://glama.ai/api/gateway/openai/v1/chat/completions').trim();
const GLAMA_API_KEY = (process.env.GLAMA_API_KEY || '').trim();
const GLAMA_MODEL_DEFAULT =
  (process.env.GLAMA_MODEL || process.env.GLAMA_MODEL_LLM || process.env.GLAMA_MODEL_DEFAULT || 'gpt-4o-mini').trim();
const GLAMA_TEMPERATURE = Number.isFinite(Number(process.env.GLAMA_TEMPERATURE))
  ? Number(process.env.GLAMA_TEMPERATURE)
  : 0.2;
const GLAMA_MAX_TOKENS = Number.isFinite(Number(process.env.GLAMA_MAX_TOKENS))
  ? Number(process.env.GLAMA_MAX_TOKENS)
  : 800;
const GLAMA_SYSTEM_PROMPT =
  process.env.GLAMA_SYSTEM_PROMPT || 'You are an upbeat AI assistant for Surf Thailand. Keep responses concise and helpful.';
const TALK_GUIDANCE_DEFAULT =
  (process.env.TALK_GUIDANCE_DEFAULT || 'Open with a warm greeting, ask about today’s focus, and offer two helpful follow-up prompts.').trim();
const DEPLOY_SCRIPT =
  process.env.DEPLOY_SCRIPT || path.resolve(__dirname, '..', '..', '..', 'scripts', 'pull-node-1.sh');
const PUBLIC_ROOT = path.resolve(__dirname, '..', 'public');
const TONY_SITES_ROOT = path.resolve(PUBLIC_ROOT, 'tony', 'sites');
const TONY_SITES_MANIFEST_PATH = path.resolve(__dirname, '..', 'tony-sites.json');
const AGENTS_ROOT = path.resolve(__dirname, '..', 'agents');
const AGENT_REGISTRY_PATH = path.join(AGENTS_ROOT, 'registry.json');
const DEFAULT_STATIC_BUNDLES = ['chat', 'talk'];
const RELEASE_METADATA_PATH = path.resolve(__dirname, '..', 'payload.json');
const UPLOADS_ROOT = path.resolve(__dirname, '..', 'uploads');

const sessionStore = new Map();
const ORCHESTRATOR_ID = 'orchestrator';
const DEFAULT_USER_ID = 'default';
const DATA_ROOT = path.resolve(__dirname, '..', 'data');
const SESSION_STORAGE_PATH = path.join(DATA_ROOT, 'sessions.json');
const SESSION_ARCHIVE_DIR = path.join(DATA_ROOT, 'archive', 'sessions');
const SESSION_ARCHIVE_MESSAGE_LIMIT = Number.isFinite(Number(process.env.SESSION_ARCHIVE_MESSAGE_LIMIT))
  ? Math.max(10, Number(process.env.SESSION_ARCHIVE_MESSAGE_LIMIT))
  : 200;
let sessionPersistTimer = null;
let sessionsHydrated = false;

const normalizeUserId = (value = '') => {
  const trimmed = (value || '').toString().trim().toLowerCase();
  return trimmed || DEFAULT_USER_ID;
};

const serializeSessions = () =>
  [...sessionStore.values()].map((session) => ({
    ...session,
    messages: Array.isArray(session?.messages) ? session.messages : []
  }));

const persistSessionStore = async () => {
  try {
    await fs.mkdir(DATA_ROOT, { recursive: true });
    const payload = {
      updatedAt: new Date().toISOString(),
      sessions: serializeSessions()
    };
    await fs.writeFile(SESSION_STORAGE_PATH, JSON.stringify(payload, null, 2), 'utf8');
  } catch (error) {
    console.error('[site-man] Failed to persist sessions', error);
  }
};

const scheduleSessionPersist = () => {
  if (sessionPersistTimer) {
    return;
  }
  sessionPersistTimer = setTimeout(() => {
    sessionPersistTimer = null;
    persistSessionStore();
  }, 250);
};

const hydrateSessionStore = async () => {
  if (sessionsHydrated) {
    return;
  }
  try {
    const raw = await fs.readFile(SESSION_STORAGE_PATH, 'utf8');
    const parsed = JSON.parse(raw);
    const sessions = Array.isArray(parsed?.sessions) ? parsed.sessions : Array.isArray(parsed) ? parsed : [];
    sessions.forEach((session) => {
      if (session?.id) {
        sessionStore.set(session.id, {
          ...session,
          messages: Array.isArray(session.messages) ? session.messages : []
        });
      }
    });
  } catch (error) {
    if (error?.code !== 'ENOENT') {
      console.error('[site-man] Failed to load sessions', error);
    }
  } finally {
    sessionsHydrated = true;
  }
};

await hydrateSessionStore();

const generateId = () =>
  typeof crypto.randomUUID === 'function' ? crypto.randomUUID() : crypto.randomBytes(16).toString('hex');

const readJsonFile = async (filePath, fallback = null) => {
  try {
    const raw = await fs.readFile(filePath, 'utf8');
    return JSON.parse(raw);
  } catch (error) {
    if (error && error.code === 'ENOENT') {
      return fallback;
    }
    throw error;
  }
};

const extractTargets = (requestedIds, sessionAgents) => {
  const ids = Array.isArray(requestedIds) && requestedIds.length ? requestedIds : sessionAgents;
  return ids.filter((id) => sessionAgents.includes(id));
};

const parseDelegationPlan = (content, sessionAgents = []) => {
  if (!content) {
    return [];
  }
  const actions = [];
  const lines = content.split(/\r?\n/);
  const agentSet = new Set(sessionAgents.filter((id) => id !== ORCHESTRATOR_ID));
  const pattern = /^\s*([a-z0-9_-]{2,})\s*[:\-]\s*(.+)$/i;
  for (const line of lines) {
    const match = line.match(pattern);
    if (!match) {
      continue;
    }
    const agentId = match[1].toLowerCase();
    const instruction = match[2].trim();
    if (!instruction || !agentSet.has(agentId)) {
      continue;
    }
    actions.push({ agentId, instruction });
  }
  return actions;
};

const enqueueDelegations = ({ session, delegations }) => {
  if (!delegations || !delegations.length) {
    return;
  }
  delegations.forEach(({ agentId, instruction }) => {
    const message = {
      id: generateId(),
      role: 'user',
      content: instruction,
      agentTargets: [agentId],
      createdAt: new Date().toISOString()
    };
    appendSessionMessage(session.id, message);
  });
};

const uniqueAgents = (ids = []) => [...new Set(ids.filter(Boolean))];

const runOrchestratorIfNeeded = async ({ session, targets, onComplete, onError }) => {
  if (!targets.includes(ORCHESTRATOR_ID)) {
    return { targets }; 
  }

  try {
    const response = await runAgentResponse({ session, agentId: ORCHESTRATOR_ID });
    if (typeof onComplete === 'function') {
      onComplete(response);
    }
    const filtered = targets.filter((id) => id !== ORCHESTRATOR_ID);
    const delegations = parseDelegationPlan(response?.content || '', session.agents);
    enqueueDelegations({ session, delegations });
    const delegatedAgents = delegations.length ? uniqueAgents(delegations.map((item) => item.agentId)) : filtered;
    return { targets: delegatedAgents, orchestratorResponse: response, delegations };
  } catch (error) {
    if (typeof onError === 'function') {
      onError(error);
    }
    throw error;
  }
};

const listAgentEntries = async () => {
  const registry = (await readJsonFile(AGENT_REGISTRY_PATH, null)) || {};
  return Array.isArray(registry?.agents) ? registry.agents : [];
};

const resolveAgentPaths = (entry = {}) => {
  const relativePath = entry.path || `./${entry.id}`;
  const dir = path.resolve(AGENTS_ROOT, relativePath);
  return {
    dir,
    configPath: path.join(dir, 'config.json')
  };
};

const loadAgentDescriptor = async (agentId, registryEntries = null) => {
  const entries = registryEntries || (await listAgentEntries());
  const entry = entries.find((agent) => agent.id === agentId);
  if (!entry) {
    return null;
  }

  const paths = resolveAgentPaths(entry);
  const config = await readJsonFile(paths.configPath, null);

  return {
    entry,
    config,
    ...paths
  };
};

const describeAgents = async () => {
  const entries = await listAgentEntries();
  return Promise.all(
    entries.map(async (entry) => {
      const descriptor = await loadAgentDescriptor(entry.id, entries);
      return {
        ...entry,
        configAvailable: Boolean(descriptor?.config)
      };
    })
  );
};

const normalizeSessionMetadata = (metadata) => {
  const base = {
    title: null,
    pinned: false,
    autoTitle: true
  };
  if (!metadata) {
    return base;
  }
  return {
    ...base,
    ...metadata,
    pinned: Boolean(metadata.pinned),
    autoTitle: metadata.autoTitle === false ? false : true,
    title: typeof metadata.title === 'string' && metadata.title.trim() ? metadata.title.trim() : base.title
  };
};

const createSessionRecord = ({ userId, agents, metadata }) => {
  const now = new Date().toISOString();
  const session = {
    id: generateId(),
    userId: normalizeUserId(userId),
    agents,
    metadata: normalizeSessionMetadata(metadata),
    createdAt: now,
    updatedAt: now,
    messages: []
  };
  sessionStore.set(session.id, session);
  scheduleSessionPersist();
  return session;
};

const appendSessionMessage = (sessionId, message) => {
  const session = sessionStore.get(sessionId);
  if (!session) {
    return null;
  }
  session.messages.push(message);
  session.updatedAt = message.createdAt;
  scheduleSessionPersist();
  return message;
};

const removeSession = (sessionId) => {
  if (!sessionId) {
    return false;
  }
  const removed = sessionStore.delete(sessionId);
  if (removed) {
    scheduleSessionPersist();
  }
  return removed;
};

const DEFAULT_AGENT_PROMPT = 'You are a helpful Surf Thailand assistant. Respond with concise, actionable information.';

const getSessionForUser = (userId, sessionId) => {
  const session = sessionStore.get(sessionId);
  if (!session) {
    return null;
  }
  return session.userId === normalizeUserId(userId) ? session : null;
};

const listSessionsForUser = (userId, { limit = 20 } = {}) => {
  const normalized = normalizeUserId(userId);
  const sessions = [...sessionStore.values()].filter((session) => session.userId === normalized);
  sessions.sort((a, b) => {
    const aPinned = Boolean(a.metadata?.pinned);
    const bPinned = Boolean(b.metadata?.pinned);
    if (aPinned !== bPinned) {
      return aPinned ? -1 : 1;
    }
    return new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime();
  });
  return sessions.slice(0, limit);
};

const updateSessionMetadata = (session, patch = {}) => {
  if (!session) {
    return null;
  }
  session.metadata = {
    ...normalizeSessionMetadata(session.metadata),
    ...patch,
    title:
      typeof patch.title === 'string' && patch.title.trim() ? patch.title.trim() : patch.title === null ? null : session.metadata?.title,
    pinned: typeof patch.pinned === 'boolean' ? patch.pinned : Boolean(session.metadata?.pinned),
    autoTitle: typeof patch.autoTitle === 'boolean' ? patch.autoTitle : session.metadata?.autoTitle !== false
  };
  scheduleSessionPersist();
  return session.metadata;
};

const buildAutoTitlePrompt = (session) => {
  const recent = session.messages.slice(-8);
  const lines = recent.map((message) => {
    const role = message.role === 'assistant' ? (message.agentId || 'assistant') : 'user';
    return `${role}: ${message.content}`;
  });
  const content = lines.join('\n').slice(0, 1000);
  return [
    { role: 'system', content: 'You are an assistant that writes short, descriptive chat titles (max 6 words).' },
    {
      role: 'user',
      content: `Conversation excerpt:\n${content}\n\nRespond with a concise title (no quotes).`
    }
  ];
};

const generateSessionTitle = async (session) => {
  const messages = buildAutoTitlePrompt(session);
  const { text } = await callGlamaChatCompletion({ messages, maxTokens: 32, temperature: 0.3 });
  const processed = (text || '').split('\n')[0].trim();
  return processed.slice(0, 80) || 'Conversation';
};

const buildSessionSummaryPrompt = (session) => {
  const recent = session.messages.slice(-12);
  const excerpt = recent
    .map((message) => {
      const role = message.role === 'assistant' ? (message.agentId || 'assistant') : 'user';
      return `${role}: ${message.content}`;
    })
    .join('\n')
    .slice(0, 1600);
  return [
    {
      role: 'system',
      content:
        'You are an operations assistant who summarizes multi-agent conversations. Provide 2-3 sentences plus optional bullet reminders.'
    },
    {
      role: 'user',
      content: `Conversation excerpt:\n${excerpt}\n\nSummarize key goals, actions, blockers, and next steps.`
    }
  ];
};

const summarizeSessionContext = async (session) => {
  if (!session?.messages?.length) {
    return 'Session contained no messages.';
  }
  const fallback = () =>
    session.messages
      .slice(-5)
      .map((message) => {
        const role = message.role === 'assistant' ? (message.agentId || 'assistant') : 'user';
        return `${role}: ${message.content}`;
      })
      .join('\n');

  if (!isGlamaReady()) {
    return fallback();
  }

  try {
    const prompt = buildSessionSummaryPrompt(session);
    const { text } = await callGlamaChatCompletion({ messages: prompt, maxTokens: 160, temperature: 0.2 });
    return (text || '').trim() || fallback();
  } catch (error) {
    console.error('[site-man] session summary failed', error);
    return fallback();
  }
};

const trimMessagesForArchive = (messages = [], limit = SESSION_ARCHIVE_MESSAGE_LIMIT) =>
  messages.slice(-limit).map((message) => ({
    id: message.id,
    role: message.role,
    agentId: message.agentId || null,
    content: message.content,
    agentTargets: Array.isArray(message.agentTargets) ? message.agentTargets : null,
    attachments: Array.isArray(message.attachments) ? message.attachments : null,
    createdAt: message.createdAt
  }));

const buildSessionArchiveRecord = async ({ session, deletedBy, reason }) => {
  const summary = await summarizeSessionContext(session);
  return {
    sessionId: session.id,
    userId: session.userId,
    agents: session.agents,
    metadata: session.metadata || null,
    createdAt: session.createdAt,
    updatedAt: session.updatedAt,
    deletedAt: new Date().toISOString(),
    deletedBy: deletedBy || 'system',
    reason: reason || null,
    summary,
    messageCount: Array.isArray(session.messages) ? session.messages.length : 0,
    storedMessages: trimMessagesForArchive(session.messages)
  };
};

const persistSessionArchiveRecord = async (record) => {
  await fs.mkdir(SESSION_ARCHIVE_DIR, { recursive: true });
  const archiveId = record.archiveId || `${record.sessionId}-${Date.now()}`;
  const filename = `${archiveId}.json`;
  const archivePath = path.join(SESSION_ARCHIVE_DIR, filename);
  const payload = {
    ...record,
    archiveId
  };
  await fs.writeFile(archivePath, JSON.stringify(payload, null, 2), 'utf8');
  return { archiveId, archivePath };
};

const readArchiveRecord = async (archiveId) => {
  if (!archiveId) {
    return null;
  }
  const archivePath = path.join(SESSION_ARCHIVE_DIR, `${archiveId}.json`);
  try {
    const raw = await fs.readFile(archivePath, 'utf8');
    return JSON.parse(raw);
  } catch (error) {
    if (error.code !== 'ENOENT') {
      console.error('[site-man] read archive failed', archiveId, error);
    }
    return null;
  }
};

const listArchiveRecordsForUser = async ({ userId, limit = 20 }) => {
  const normalized = normalizeUserId(userId);
  let files = [];
  try {
    files = await fs.readdir(SESSION_ARCHIVE_DIR);
  } catch (error) {
    if (error.code === 'ENOENT') {
      return [];
    }
    throw error;
  }

  const records = [];
  for (const file of files) {
    if (!file.endsWith('.json')) {
      continue;
    }
    const archiveId = file.replace(/\.json$/, '');
    const record = await readArchiveRecord(archiveId);
    if (!record || record.userId !== normalized) {
      continue;
    }
    records.push(record);
  }

  records.sort((a, b) => {
    const aTime = new Date(a.deletedAt || a.updatedAt || 0).getTime();
    const bTime = new Date(b.deletedAt || b.updatedAt || 0).getTime();
    return bTime - aTime;
  });

  return records.slice(0, Math.max(1, Math.min(100, limit)));
};

const buildMessagesForAgent = ({ session, agentId, systemPrompt, historyLimit = 20 }) => {
  const messages = [];
  messages.push({ role: 'system', content: systemPrompt || DEFAULT_AGENT_PROMPT });
  const recent = session.messages.slice(-historyLimit);
  for (const entry of recent) {
    if (entry.role === 'user') {
      if (!entry.agentTargets || entry.agentTargets.includes(agentId)) {
        messages.push({ role: 'user', content: entry.content });
      }
    } else if (entry.role === 'assistant' && entry.agentId === agentId) {
      messages.push({ role: 'assistant', content: entry.content });
    }
  }
  return messages;
};

const runAgentResponse = async ({ session, agentId }) => {
  const descriptor = await loadAgentDescriptor(agentId);
  if (!descriptor || !descriptor.config) {
    throw new Error('agent_config_missing');
  }

  const config = descriptor.config;
  const systemPrompt = config?.persona?.systemPrompt || DEFAULT_AGENT_PROMPT;
  const messages = buildMessagesForAgent({ session, agentId, systemPrompt });

  const modelSettings = config?.model || {};
  const { text, data } = await callGlamaChatCompletion({
    messages,
    model: modelSettings.defaultModel,
    temperature: modelSettings.temperature,
    maxTokens: modelSettings.maxTokens
  });

  const response = {
    id: generateId(),
    role: 'assistant',
    agentId,
    content: text,
    createdAt: new Date().toISOString(),
    metadata: {
      model: modelSettings.defaultModel || GLAMA_MODEL_DEFAULT,
      provider: 'glama',
      raw: data
    }
  };

  appendSessionMessage(session.id, response);
  return response;
};

const streamGlamaChatCompletion = async ({ messages, model, maxTokens, temperature, onToken }) => {
  if (!isGlamaReady()) {
    throw new Error('glama_unconfigured');
  }
  if (!Array.isArray(messages) || !messages.length) {
    throw new Error('messages_required');
  }

  const payload = {
    model: model || GLAMA_MODEL_DEFAULT,
    max_tokens: Number.isFinite(maxTokens) && maxTokens > 0 ? maxTokens : GLAMA_MAX_TOKENS,
    temperature: typeof temperature === 'number' ? temperature : GLAMA_TEMPERATURE,
    stream: true,
    messages
  };

  const response = await fetch(GLAMA_API_URL, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${GLAMA_API_KEY}`
    },
    body: JSON.stringify(payload)
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `glama_http_${response.status}`);
  }

  if (!response.body || typeof response.body.getReader !== 'function') {
    throw new Error('glama_stream_unsupported');
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder('utf8');
  let buffer = '';
  let accumulated = '';
  let doneStreaming = false;

  while (!doneStreaming) {
    const { value, done } = await reader.read();
    if (done && (!value || value.length === 0)) {
      break;
    }
    buffer += decoder.decode(value || new Uint8Array(), { stream: true });

    let boundary = buffer.indexOf('\n\n');
    while (boundary !== -1) {
      const rawChunk = buffer.slice(0, boundary).trim();
      buffer = buffer.slice(boundary + 2);
      if (rawChunk.startsWith('data:')) {
        const data = rawChunk.slice(5).trim();
        if (!data) {
          boundary = buffer.indexOf('\n\n');
          continue;
        }
        if (data === '[DONE]') {
          doneStreaming = true;
          break;
        }
        try {
          const parsed = JSON.parse(data);
          const deltas = Array.isArray(parsed?.choices)
            ? parsed.choices.map((choice) => choice?.delta?.content || '').filter(Boolean)
            : [];
          if (deltas.length) {
            const deltaText = deltas.join('');
            accumulated += deltaText;
            if (typeof onToken === 'function') {
              onToken(deltaText, parsed);
            }
          }
        } catch (error) {
          // ignore malformed chunk
        }
      }
      boundary = buffer.indexOf('\n\n');
    }
    if (done) {
      doneStreaming = true;
    }
  }

  return { text: accumulated };
};

const streamAgentResponse = async ({ session, agentId, onDelta }) => {
  const descriptor = await loadAgentDescriptor(agentId);
  if (!descriptor || !descriptor.config) {
    throw new Error('agent_config_missing');
  }

  const config = descriptor.config;
  const systemPrompt = config?.persona?.systemPrompt || DEFAULT_AGENT_PROMPT;
  const messages = buildMessagesForAgent({ session, agentId, systemPrompt });

  const modelSettings = config?.model || {};
  const { text } = await streamGlamaChatCompletion({
    messages,
    model: modelSettings.defaultModel,
    temperature: modelSettings.temperature,
    maxTokens: modelSettings.maxTokens,
    onToken: (delta, chunk) => {
      if (typeof onDelta === 'function') {
        onDelta(delta, chunk);
      }
    }
  });

  const response = {
    id: generateId(),
    role: 'assistant',
    agentId,
    content: text || '',
    createdAt: new Date().toISOString(),
    metadata: {
      model: modelSettings.defaultModel || GLAMA_MODEL_DEFAULT,
      provider: 'glama',
      streamed: true
    }
  };

  appendSessionMessage(session.id, response);
  return response;
};

const rawBodyBuffer = (req, _res, buffer) => {
  if (buffer && buffer.length) {
    req.rawBody = buffer.toString('utf8');
  }
};

const isGlamaReady = () => Boolean(GLAMA_API_KEY && GLAMA_API_URL);

const ensureGlamaReady = (res) => {
  if (!isGlamaReady()) {
    res.status(503).json({ error: 'glama_unconfigured' });
    return false;
  }
  return true;
};

const callGlamaChatCompletion = async ({ messages, model, maxTokens, temperature }) => {
  if (!isGlamaReady()) {
    throw new Error('glama_unconfigured');
  }
  if (!Array.isArray(messages) || !messages.length) {
    throw new Error('messages_required');
  }

  const payload = {
    model: model || GLAMA_MODEL_DEFAULT,
    max_tokens: Number.isFinite(maxTokens) && maxTokens > 0 ? maxTokens : GLAMA_MAX_TOKENS,
    temperature: typeof temperature === 'number' ? temperature : GLAMA_TEMPERATURE,
    messages
  };

  const response = await fetch(GLAMA_API_URL, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${GLAMA_API_KEY}`
    },
    body: JSON.stringify(payload)
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `glama_http_${response.status}`);
  }

  const data = await response.json();
  const text = Array.isArray(data?.choices)
    ? data.choices
        .map((choice) => choice?.message?.content || '')
        .filter(Boolean)
        .join('\n')
        .trim()
    : '';

  return { text, data };
};

const restartNodeDomain = () =>
  new Promise((resolve) => {
    if (!NODE_DOMAIN) {
      return resolve({ restarted: false, reason: 'node_domain_missing' });
    }

    const child = spawn('plesk', ['bin', 'nodejs', '--restart', NODE_DOMAIN], {
      stdio: 'inherit'
    });

    child.on('error', (error) => {
      console.error('[site-man] Failed to restart Node domain', error);
      resolve({ restarted: false, error: error.message });
    });

    child.on('close', (code) => {
      if (code === 0) {
        resolve({ restarted: true });
      } else {
        resolve({ restarted: false, reason: `plesk_exit_${code}` });
      }
    });
  });

const normalizeSiteSlug = (value = '') =>
  value
    .toString()
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9-_]/g, '-')
    .replace(/-+/g, '-')
    .replace(/^-|-$/g, '');

const normalizeRelativePath = (value = '') =>
  value
    .toString()
    .trim()
    .replace(/^[./\\]+/, '')
    .replace(/\\/g, '/');

const isWithinPath = (parent, child) => {
  const relative = path.relative(parent, child);
  return Boolean(relative) ? !relative.startsWith('..') && !path.isAbsolute(relative) : true;
};

const describeStaticBundle = async (bundleName) => {
  const summary = {
    name: bundleName,
    exists: false,
    files: 0,
    bytes: 0,
    updatedAt: null,
    sampleEntries: []
  };

  const bundlePath = path.join(PUBLIC_ROOT, bundleName);
  try {
    const stats = await fs.stat(bundlePath);
    if (!stats.isDirectory()) {
      return summary;
    }

    summary.exists = true;
    let latest = stats.mtimeMs;
    const stack = [{ dir: bundlePath, relative: '' }];
    while (stack.length) {
      const { dir, relative } = stack.pop();
      const entries = await fs.readdir(dir, { withFileTypes: true });
      for (const entry of entries) {
        const entryPath = path.join(dir, entry.name);
        const relPath = path.join(relative, entry.name).replace(/\\/g, '/');
        const entryStats = await fs.stat(entryPath);
        latest = Math.max(latest, entryStats.mtimeMs);
        if (entry.isDirectory()) {
          stack.push({ dir: entryPath, relative: relPath });
          if (summary.sampleEntries.length < 10) {
            summary.sampleEntries.push({ path: `${relPath}/`, size: null });
          }
        } else {
          summary.files += 1;
          summary.bytes += entryStats.size;
          if (summary.sampleEntries.length < 10) {
            summary.sampleEntries.push({ path: relPath, size: entryStats.size });
          }
        }
      }
    }
    summary.updatedAt = new Date(latest).toISOString();
  } catch (error) {
    if (error.code !== 'ENOENT') {
      console.error('[site-man] static bundle inspection failed', bundleName, error);
    }
  }

  return summary;
};

const describeStaticBundles = async (names = DEFAULT_STATIC_BUNDLES) => {
  const normalized = Array.isArray(names) && names.length ? names : DEFAULT_STATIC_BUNDLES;
  const unique = [...new Set(normalized.filter(Boolean))];
  return Promise.all(unique.map((name) => describeStaticBundle(name)));
};

const readReleaseMetadata = async () => {
  try {
    const raw = await fs.readFile(RELEASE_METADATA_PATH, 'utf8');
    return JSON.parse(raw);
  } catch (error) {
    if (error.code !== 'ENOENT') {
      console.error('[site-man] release metadata read failed', error);
    }
    return null;
  }
};

const formatRegexpSource = (regexp) => {
  if (!regexp) {
    return '';
  }
  if (regexp.fast_slash) {
    return '/';
  }
  return regexp.toString();
};

const describeRouteStack = (stack = []) =>
  stack
    .filter((layer) => layer && typeof layer.handle === 'function')
    .map((layer, index) => ({
      index,
      type: layer.route ? 'route' : layer.name === 'serveStatic' ? 'static' : 'middleware',
      name: layer.name || '(anonymous)',
      path: layer.route?.path || formatRegexpSource(layer.regexp),
      methods: layer.route ? Object.keys(layer.route.methods).map((method) => method.toUpperCase()) : undefined
    }));

const talkRouter = express.Router();
talkRouter.use(
  express.static(path.join(PUBLIC_ROOT, 'talk'), {
    extensions: ['html', 'htm']
  })
);

app.use(morgan('dev'));
app.use(express.json({ limit: '25mb', verify: rawBodyBuffer }));
app.use('/uploads', express.static(UPLOADS_ROOT));

app.use('/tony/:siteSlug', (req, res, next) => {
  const siteSlug = normalizeSiteSlug(req.params.siteSlug);
  if (!siteSlug) {
    return res.status(404).send('Site not found');
  }

  const siteRoot = path.join(TONY_SITES_ROOT, siteSlug);
  const staticMiddleware = express.static(siteRoot, {
    extensions: ['html', 'htm']
  });

  return staticMiddleware(req, res, (err) => {
    if (err && err.status === 404) {
      return res.status(404).send('Site not found');
    }
    if (err) {
      return next(err);
    }
    return next();
  });
});

app.use(
  '/tony/sites',
  express.static(TONY_SITES_ROOT, {
    extensions: ['html', 'htm']
  })
);

const CHAT_PUBLIC_DIR = path.join(__dirname, '..', 'public', 'chat');
app.use(
  '/chat',
  express.static(CHAT_PUBLIC_DIR, {
    extensions: ['html', 'htm']
  })
);
const serveChatBundle = (_req, res) => {
  res.sendFile(path.join(CHAT_PUBLIC_DIR, 'index.html'));
};
app.get(['/chat', '/chat/:userId'], serveChatBundle);
app.get('/chat/:userId/*', serveChatBundle);

app.use('/talk', talkRouter);

app.get('/api/agents', async (_req, res) => {
  try {
    const agents = await describeAgents();
    res.json({ agents });
  } catch (error) {
    console.error('[site-man] list agents failed', error);
    res.status(500).json({ error: 'agents_list_failed' });
  }
});

app.get('/api/users/:userId/sessions/:sessionId/stream', async (req, res) => {
  if (!ensureGlamaReady(res)) {
    return;
  }

  const userId = normalizeUserId(req.params.userId);
  const session = getSessionForUser(userId, req.params.sessionId);
  if (!session) {
    return res.status(404).json({ error: 'session_not_found' });
  }

  const requested = typeof req.query.agents === 'string'
    ? req.query.agents.split(',').map((id) => id.trim()).filter(Boolean)
    : null;
  let targets = extractTargets(requested, session.agents);
  if (!targets.length) {
    return res.status(400).json({ error: 'agents_required' });
  }

  res.setHeader('Content-Type', 'text/event-stream');
  res.setHeader('Cache-Control', 'no-cache');
  res.setHeader('Connection', 'keep-alive');
  res.flushHeaders();

  const sendEvent = (event, payload) => {
    res.write(`event: ${event}\n`);
    res.write(`data: ${JSON.stringify(payload)}\n\n`);
  };

  let aborted = false;
  req.on('close', () => {
    aborted = true;
  });

  try {
    const orchestratorResults = await runOrchestratorIfNeeded({
      session,
      targets,
      onComplete: (message) => {
        sendEvent('complete', { agentId: ORCHESTRATOR_ID, message });
      },
      onError: (error) => {
        sendEvent('stream-error', { agentId: ORCHESTRATOR_ID, error: error.message || 'agent_stream_failed' });
      }
    });
    targets = orchestratorResults.targets;
  } catch (error) {
    sendEvent('stream-error', { agentId: ORCHESTRATOR_ID, error: error.message || 'agent_stream_failed' });
    sendEvent('done', { sessionId: session.id });
    return res.end();
  }

  if (!targets.length) {
    sendEvent('done', { sessionId: session.id });
    return res.end();
  }

  const runStreams = targets.map((agentId) =>
    streamAgentResponse({
      session,
      agentId,
      onDelta: (delta) => {
        sendEvent('token', { agentId, delta });
      }
    })
      .then((response) => {
        sendEvent('complete', { agentId, message: response });
        return response;
      })
      .catch((error) => {
        console.error('[site-man] stream agent failed', error);
        sendEvent('stream-error', { agentId, error: error.message || 'agent_stream_failed' });
      })
  );

  Promise.all(runStreams)
    .finally(() => {
      if (!aborted) {
        sendEvent('done', { sessionId: session.id });
        res.end();
      }
    })
    .catch(() => {
      if (!aborted) {
        sendEvent('done', { sessionId: session.id });
        res.end();
      }
    });
});

app.get('/api/talk/guidance', (_req, res) => {
  res.json({ guidance: TALK_GUIDANCE_DEFAULT });
});

app.use(express.static(path.join(__dirname, '..', 'public')));

app.get('/api/agents/:agentId', async (req, res) => {
  try {
    const descriptor = await loadAgentDescriptor(req.params.agentId);
    if (!descriptor) {
      return res.status(404).json({ error: 'agent_not_found' });
    }
    const { entry, config } = descriptor;
    return res.json({ agent: { ...entry, config } });
  } catch (error) {
    console.error('[site-man] agent lookup failed', error);
    res.status(500).json({ error: 'agent_lookup_failed' });
  }
});

app.post('/api/sessions', async (req, res) => {
  try {
    const requested = Array.isArray(req.body?.agents)
      ? [...new Set(req.body.agents.map((id) => (id || '').toString().trim()).filter(Boolean))]
      : [];

    if (!requested.length) {
      return res.status(400).json({ error: 'agents_required' });
    }

    const registryEntries = await listAgentEntries();
    const missing = requested.filter((id) => !registryEntries.some((entry) => entry.id === id));
    if (missing.length) {
      return res.status(404).json({ error: 'agent_not_registered', detail: missing });
    }

    const session = createSessionRecord({ agents: requested, metadata: req.body?.metadata || null });
    return res.status(201).json({ session });
  } catch (error) {
    console.error('[site-man] create session failed', error);
    res.status(500).json({ error: 'session_create_failed' });
  }
});

app.get('/api/users/:userId/sessions/:sessionId', (req, res) => {
  const userId = normalizeUserId(req.params.userId);
  const session = getSessionForUser(userId, req.params.sessionId);
  if (!session) {
    return res.status(404).json({ error: 'session_not_found' });
  }
  return res.json({ session });
});

app.get('/api/users/:userId/sessions', (req, res) => {
  const userId = normalizeUserId(req.params.userId);
  const limit = Number.parseInt(req.query?.limit, 10);
  const max = Number.isFinite(limit) && limit > 0 ? Math.min(limit, 50) : 20;
  const sessions = listSessionsForUser(userId, { limit: max }).map((session) => ({
    id: session.id,
    agents: session.agents,
    createdAt: session.createdAt,
    updatedAt: session.updatedAt,
    metadata: session.metadata || null,
    messageCount: Array.isArray(session.messages) ? session.messages.length : 0
  }));
  return res.json({ sessions });
});

app.post('/api/users/:userId/sessions', async (req, res) => {
  try {
    const userId = normalizeUserId(req.params.userId);
    const requested = Array.isArray(req.body?.agents)
      ? [...new Set(req.body.agents.map((id) => (id || '').toString().trim()).filter(Boolean))]
      : [];

    if (!requested.length) {
      return res.status(400).json({ error: 'agents_required' });
    }

    const registryEntries = await listAgentEntries();
    const missing = requested.filter((id) => !registryEntries.some((entry) => entry.id === id));
    if (missing.length) {
      return res.status(404).json({ error: 'agent_not_registered', detail: missing });
    }

    const session = createSessionRecord({ agents: requested, metadata: req.body?.metadata || null, userId });
    return res.status(201).json({ session });
  } catch (error) {
    console.error('[site-man] create session failed', error);
    res.status(500).json({ error: 'session_create_failed' });
  }
});

app.patch('/api/users/:userId/sessions/:sessionId', (req, res) => {
  const userId = normalizeUserId(req.params.userId);
  const session = getSessionForUser(userId, req.params.sessionId);
  if (!session) {
    return res.status(404).json({ error: 'session_not_found' });
  }
  const patch = {};
  if ('title' in req.body) {
    patch.title = typeof req.body.title === 'string' ? req.body.title : null;
    patch.autoTitle = false;
  }
  if ('pinned' in req.body) {
    patch.pinned = Boolean(req.body.pinned);
  }
  updateSessionMetadata(session, patch);
  return res.json({ metadata: session.metadata });
});

app.post('/api/users/:userId/sessions/:sessionId/auto-title', async (req, res) => {
  if (!ensureGlamaReady(res)) {
    return;
  }
  try {
    const userId = normalizeUserId(req.params.userId);
    const session = getSessionForUser(userId, req.params.sessionId);
    if (!session) {
      return res.status(404).json({ error: 'session_not_found' });
    }
    if (!session.messages.length) {
      return res.status(400).json({ error: 'session_empty' });
    }
    const title = await generateSessionTitle(session);
    updateSessionMetadata(session, { title, autoTitle: true });
    return res.json({ title });
  } catch (error) {
    console.error('[site-man] auto-title failed', error);
    return res.status(500).json({ error: 'auto_title_failed', detail: error.message || 'unknown_error' });
  }
});

app.delete('/api/users/:userId/sessions/:sessionId', async (req, res) => {
  const userId = normalizeUserId(req.params.userId);
  const session = getSessionForUser(userId, req.params.sessionId);
  if (!session) {
    return res.status(404).json({ error: 'session_not_found' });
  }

  try {
    const record = await buildSessionArchiveRecord({
      session,
      deletedBy: req.get('x-session-deleted-by') || 'user_request',
      reason: req.body?.reason || null
    });
    const { archiveId, archivePath } = await persistSessionArchiveRecord(record);
    removeSession(session.id);
    return res.json({ archived: true, archiveId, archivePath, summary: record.summary });
  } catch (error) {
    console.error('[site-man] delete session failed', error);
    return res.status(500).json({ error: 'session_delete_failed', detail: error.message || 'unknown_error' });
  }
});

app.get('/api/users/:userId/archives', async (req, res) => {
  try {
    const userId = normalizeUserId(req.params.userId);
    const limitParam = Number.parseInt(req.query?.limit, 10);
    const limit = Number.isFinite(limitParam) && limitParam > 0 ? limitParam : 20;
    const archives = await listArchiveRecordsForUser({ userId, limit });
    const payload = archives.map((record) => ({
      archiveId: record.archiveId,
      sessionId: record.sessionId,
      summary: record.summary,
      agents: record.agents,
      messageCount: record.messageCount,
      deletedAt: record.deletedAt,
      deletedBy: record.deletedBy || null,
      reason: record.reason || null
    }));
    res.json({ archives: payload });
  } catch (error) {
    console.error('[site-man] list archives failed', error);
    res.status(500).json({ error: 'archives_list_failed' });
  }
});

app.get('/api/users/:userId/archives/:archiveId', async (req, res) => {
  try {
    const userId = normalizeUserId(req.params.userId);
    const archive = await readArchiveRecord(req.params.archiveId);
    if (!archive || archive.userId !== userId) {
      return res.status(404).json({ error: 'archive_not_found' });
    }
    res.json({ archive });
  } catch (error) {
    console.error('[site-man] read archive failed', error);
    res.status(500).json({ error: 'archive_read_failed' });
  }
});

app.get('/api/sessions/:sessionId', (req, res) => {
  const session = sessionStore.get(req.params.sessionId);
  if (!session) {
    return res.status(404).json({ error: 'session_not_found' });
  }
  return res.json({ session });
});

app.post('/api/sessions/:sessionId/messages', (req, res) => {
  const session = sessionStore.get(req.params.sessionId);
  if (!session) {
    return res.status(404).json({ error: 'session_not_found' });
  }

  const role = typeof req.body?.role === 'string' ? req.body.role : 'user';
  const content = typeof req.body?.content === 'string' ? req.body.content.trim() : '';
  if (!content) {
    return res.status(400).json({ error: 'content_required' });
  }

  const agentTargets = Array.isArray(req.body?.agentTargets)
    ? req.body.agentTargets.map((id) => (id || '').toString().trim()).filter(Boolean)
    : null;
  const attachments = Array.isArray(req.body?.attachments)
    ? req.body.attachments.map((item) => ({
        id: item?.id,
        name: item?.name,
        type: item?.type,
        url: item?.url,
        size: item?.size
      }))
    : null;

  const message = {
    id: generateId(),
    role,
    content,
    agentTargets: agentTargets && agentTargets.length ? agentTargets : null,
    attachments: attachments && attachments.length ? attachments : null,
    createdAt: new Date().toISOString()
  };

  appendSessionMessage(session.id, message);
  return res.status(201).json({ message });
});

app.post('/api/users/:userId/attachments', async (req, res) => {
  try {
    const userId = normalizeUserId(req.params.userId);
    const name = typeof req.body?.name === 'string' ? req.body.name.trim() : '';
    const type = typeof req.body?.type === 'string' ? req.body.type.trim() : 'application/octet-stream';
    const data = typeof req.body?.data === 'string' ? req.body.data : '';
    if (!name || !data) {
      return res.status(400).json({ error: 'invalid_attachment' });
    }

    const userUploadsDir = path.join(UPLOADS_ROOT, userId);
    await fs.mkdir(userUploadsDir, { recursive: true });
    const id = generateId();
    const filePath = path.join(userUploadsDir, id);
    const buffer = Buffer.from(data, 'base64');
    await fs.writeFile(filePath, buffer);

    const attachment = {
      id,
      name,
      type,
      size: buffer.length,
      url: `/uploads/${userId}/${id}`
    };
    return res.status(201).json({ attachment });
  } catch (error) {
    console.error('[site-man] attachment upload failed', error);
    return res.status(500).json({ error: 'attachment_upload_failed', detail: error.message || 'unknown_error' });
  }
});

app.post('/api/users/:userId/sessions/:sessionId/run', async (req, res) => {
  if (!ensureGlamaReady(res)) {
    return;
  }

  const userId = normalizeUserId(req.params.userId);
  const session = getSessionForUser(userId, req.params.sessionId);
  if (!session) {
    return res.status(404).json({ error: 'session_not_found' });
  }

  const requested = Array.isArray(req.body?.agents)
    ? [...new Set(req.body.agents.map((id) => (id || '').toString().trim()).filter(Boolean))]
    : null;

  let targets = (requested && requested.length ? requested : session.agents).filter((id) => session.agents.includes(id));
  if (!targets.length) {
    return res.status(400).json({ error: 'agents_required' });
  }

  try {
    const orchestratorResults = await runOrchestratorIfNeeded({ session, targets, onComplete: null, onError: null });
    const orderedTargets = orchestratorResults.delegations?.length
      ? orchestratorResults.delegations.map((item) => item.agentId)
      : orchestratorResults.targets;

    const downstreamResponses = [];
    for (const agentId of orderedTargets) {
      const response = await runAgentResponse({ session, agentId });
      downstreamResponses.push(response);
    }

    const responses = orchestratorResults.orchestratorResponse
      ? [orchestratorResults.orchestratorResponse, ...downstreamResponses]
      : downstreamResponses;
    return res.status(201).json({ responses });
  } catch (error) {
    console.error('[site-man] run agents failed', error);
    return res.status(500).json({ error: 'agent_run_failed', detail: error.message || 'unknown_error' });
  }
});

const escapeHtml = (value = '') =>
  value.replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));

const formatSiteLabel = (name) =>
  name
    .split(/[-_]/)
    .filter(Boolean)
    .map((segment) => segment.charAt(0).toUpperCase() + segment.slice(1))
    .join(' ') || name;

const readTonySitesManifest = async () => {
  try {
    const raw = await fs.readFile(TONY_SITES_MANIFEST_PATH, 'utf8');
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed?.sites) ? parsed.sites : [];
  } catch (error) {
    if (error.code !== 'ENOENT') {
      console.error('[site-man] Failed to read Tony sites manifest', error);
    }
    return [];
  }
};

const readTonySites = async () => {
  try {
    const manifest = await readTonySitesManifest();
    const entries = manifest.length
      ? manifest
      : await fs.readdir(TONY_SITES_ROOT, { withFileTypes: true }).then((dirs) =>
          dirs.filter((entry) => entry.isDirectory()).map((entry) => ({ slug: entry.name, path: entry.name }))
        );

    const sites = await Promise.all(
      entries.map(async (entry) => {
        const slug = normalizeSiteSlug(entry.slug || entry.name || entry.path || '');
        if (!slug) {
          return null;
        }
        const folderName = entry.path ? normalizeRelativePath(entry.path) : slug;
        const sitePath = path.join(TONY_SITES_ROOT, folderName);
        const indexPath = path.join(sitePath, 'index.html');
        let hasIndex = false;
        try {
          await fs.access(indexPath);
          hasIndex = true;
        } catch {
          hasIndex = false;
        }
        return {
          name: slug,
          label: entry.label || formatSiteLabel(slug),
          description: entry.description || null,
          url: `/tony/sites/${encodeURIComponent(slug)}/`,
          filesystemPath: sitePath,
          hasIndex,
          bundlePath: path.relative(PUBLIC_ROOT, sitePath).replace(/\\/g, '/')
        };
      })
    );

    return sites.filter(Boolean).sort((a, b) => a.label.localeCompare(b.label));
  } catch (error) {
    if (error.code === 'ENOENT') {
      return [];
    }
    console.error('[site-man] Failed to enumerate Tony sites', error);
    return [];
  }
};

const verifySignature = (signature, payload) => {
  if (!WEBHOOK_SECRET || typeof signature !== 'string' || !payload) {
    return false;
  }
  if (!signature.startsWith('sha256=')) {
    return false;
  }
  const provided = signature.slice('sha256='.length);
  const expected = crypto.createHmac('sha256', WEBHOOK_SECRET).update(payload).digest('hex');
  try {
    return crypto.timingSafeEqual(Buffer.from(provided, 'hex'), Buffer.from(expected, 'hex'));
  } catch {
    return false;
  }
};

const runDeployScript = () =>
  new Promise((resolve, reject) => {
    const child = spawn('bash', [DEPLOY_SCRIPT], {
      stdio: 'inherit'
    });
    child.on('error', reject);
    child.on('close', (code) => {
      if (code === 0) {
        resolve();
      } else {
        reject(new Error(`deploy_script_exit_${code}`));
      }
    });
  });

const availableLinks = [
  { path: '/', label: 'Landing page' },
  { path: '/api/health', label: 'Health check (JSON)' },
  { path: '/api/greeting?name=Surf', label: 'Greeting API' },
  { path: '/chat', label: 'Glama chat panel' },
  { path: '/logger', label: 'Logger demo' }
];

app.get('/tony', async (_req, res) => {
  try {
    const tonySites = await readTonySites();
    const sitesList = tonySites.length
      ? tonySites
          .map(
            (site) => `
          <li class="site-card">
            <div class="site-card__header">
              <span class="site-name">${escapeHtml(site.label)}</span>
              <span class="pill ${site.hasIndex ? 'pill--ok' : 'pill--warn'}">
                ${site.hasIndex ? 'index.html detected' : 'no index.html'}</span>
            </div>
            <a class="site-link" href="${site.url}" target="_blank" rel="noreferrer">
              ${site.url}
            </a>
            ${site.description ? `<p>${escapeHtml(site.description)}</p>` : ''}
            <div class="path">${escapeHtml(site.filesystemPath)}</div>
          </li>`
          )
          .join('')
      : '<li class="site-card empty">No folders found yet. Add one under \n            <code>sites/site-man/public/tony/sites</code> to have it mounted automatically.</li>';

    const bundleNames = [...DEFAULT_STATIC_BUNDLES, ...tonySites.map((site) => site.bundlePath).filter(Boolean)];

    const html = `<!doctype html>
  <html lang="en">
    <head>
      <meta charset="utf-8" />
      <meta name="viewport" content="width=device-width, initial-scale=1" />
      <title>node-1 Links</title>
      <style>
        :root {
          color-scheme: dark;
        }
        * { box-sizing: border-box; }
        body {
          font-family: 'Inter', system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
          margin: 0;
          min-height: 100vh;
          background: radial-gradient(circle at top, #1c2233 0%, #05070d 45%, #000 100%);
          color: #f5f6ff;
          display: flex;
          align-items: center;
          justify-content: center;
          padding: 2rem;
        }
        .panel {
          width: min(720px, 100%);
          background: rgba(9, 12, 26, 0.85);
          border-radius: 24px;
          padding: 2.5rem;
          box-shadow: 0 25px 60px rgba(5, 8, 20, 0.55);
          border: 1px solid rgba(126, 242, 201, 0.15);
        }
        section { margin-top: 2rem; }
        h1 {
          margin: 0 0 0.5rem;
          font-size: clamp(1.8rem, 4vw, 2.4rem);
        }
        p {
          margin: 0 0 1.5rem;
          color: #b5bdd6;
          line-height: 1.6;
        }
        ul {
          list-style: none;
          padding: 0;
          margin: 0;
          display: grid;
          gap: 1rem;
        }
        li {
          background: rgba(255, 255, 255, 0.02);
          border: 1px solid rgba(255, 255, 255, 0.08);
          border-radius: 16px;
          padding: 1rem 1.25rem;
        }
        .site-grid {
          grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
        }
        .site-card { display: flex; flex-direction: column; gap: 0.5rem; }
        .site-card.empty { grid-column: 1 / -1; text-align: center; color: #8f99b8; }
        .site-card__header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 0.5rem;
        }
        .site-name { font-size: 1.05rem; font-weight: 600; color: #f4f5ff; }
        a {
          color: #7ef2c9;
          font-weight: 600;
          text-decoration: none;
          font-size: 1rem;
        }
        a:hover { text-decoration: underline; }
        .path {
          font-family: 'JetBrains Mono', Consolas, monospace;
          color: #8f99b8;
          display: block;
          margin-top: 0.35rem;
          font-size: 0.9rem;
        }
        .badge {
          display: inline-flex;
          align-items: center;
          gap: 0.35rem;
          background: rgba(126, 242, 201, 0.1);
          color: #7ef2c9;
          border-radius: 999px;
          padding: 0.2rem 0.85rem;
          font-size: 0.85rem;
          margin-bottom: 1rem;
        }
        .pill {
          font-size: 0.75rem;
          border-radius: 999px;
          padding: 0.1rem 0.65rem;
          text-transform: uppercase;
          letter-spacing: 0.08em;
        }
        .pill--ok { background: rgba(126, 242, 201, 0.15); color: #7ef2c9; }
        .pill--warn { background: rgba(255, 180, 123, 0.15); color: #ffb47b; }
        .actions {
          border: 1px solid rgba(255, 255, 255, 0.08);
          border-radius: 16px;
          padding: 1.5rem;
          background: rgba(255, 255, 255, 0.02);
        }
        button.restart {
          appearance: none;
          border: none;
          border-radius: 999px;
          padding: 0.75rem 1.5rem;
          font-size: 1rem;
          font-weight: 600;
          background: #ffb47b;
          color: #1b0e00;
          cursor: pointer;
        }
        button.restart:disabled {
          opacity: 0.5;
          cursor: not-allowed;
        }
        .muted { color: #8f99b8; display: block; margin-top: 0.5rem; }
        .bundle-grid {
          display: grid;
          gap: 0.75rem;
          grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
        }
        .bundle-card {
          border: 1px solid rgba(255, 255, 255, 0.08);
          border-radius: 16px;
          padding: 1rem;
          background: rgba(255, 255, 255, 0.02);
          display: flex;
          flex-direction: column;
          gap: 0.35rem;
        }
        .bundle-card h3 {
          margin: 0;
          font-size: 1rem;
        }
        .bundle-card .stat {
          font-size: 0.9rem;
          color: #8f99b8;
        }
        .bundle-card .status-pill {
          align-self: flex-start;
          padding: 0.1rem 0.75rem;
          border-radius: 999px;
          font-size: 0.8rem;
          letter-spacing: 0.05em;
          text-transform: uppercase;
        }
        .bundle-card .status-pill.ok {
          background: rgba(126, 242, 201, 0.15);
          color: #7ef2c9;
        }
        .bundle-card .status-pill.warn {
          background: rgba(255, 180, 123, 0.15);
          color: #ffb47b;
        }
        .code-block {
          border: 1px solid rgba(255, 255, 255, 0.08);
          border-radius: 12px;
          padding: 1rem;
          background: rgba(0, 0, 0, 0.35);
          font-family: 'JetBrains Mono', Consolas, monospace;
          font-size: 0.85rem;
          max-height: 320px;
          overflow: auto;
          white-space: pre-wrap;
        }
        .diagnostic-actions {
          display: flex;
          gap: 0.5rem;
          margin-top: 0.75rem;
        }
        .diagnostic-actions button {
          border: 1px solid rgba(255, 255, 255, 0.2);
          background: transparent;
          color: #f5f6ff;
          border-radius: 999px;
          padding: 0.35rem 0.9rem;
          cursor: pointer;
        }
        .release-card {
          border: 1px solid rgba(255, 255, 255, 0.08);
          border-radius: 16px;
          padding: 1rem;
          background: rgba(255, 255, 255, 0.02);
          display: flex;
          flex-direction: column;
          gap: 0.25rem;
        }
        .release-card span {
          color: #8f99b8;
          font-size: 0.9rem;
        }
      </style>
    </head>
    <body>
      <main class="panel">
        <span class="badge">node-1 preview</span>
        <h1>Surf node-1 control panel</h1>
        <p>
          Quick shortcuts to the web experiences currently deployed on node-1. These endpoints are live for
          browser and iPhone webviews, so use them when verifying releases with your team.
        </p>
        <section class="actions">
          <h2>Controls</h2>
          <p>Need a clean slate? Restart the Node app exactly like the Plesk button on node-1.</p>
          <button id="restartBtn" class="restart">Restart app</button>
          <small class="muted">Requires the Tony deploy secret.</small>
        </section>
        <section>
          <h2>Core utilities</h2>
          <ul>
            ${availableLinks
              .map(
                (link) =>
                  `<li><a href="${link.path}" target="_blank" rel="noreferrer">${link.label}</a><span class="path">${link.path}</span></li>`
              )
              .join('')}
          </ul>
        </section>
        <section>
          <h2>Release metadata</h2>
          <div id="releaseInfo" class="release-card">Loading release payload…</div>
        </section>
        <section>
          <h2>Static bundles health</h2>
          <div id="bundleDiagnostics" class="bundle-grid">Loading bundle stats…</div>
          <div class="diagnostic-actions">
            <button id="refreshBundles">Refresh bundles</button>
          </div>
        </section>
        <section>
          <h2>Route stack</h2>
          <pre id="routeStack" class="code-block">Loading routes…</pre>
          <div class="diagnostic-actions">
            <button id="refreshRoutes">Refresh routes</button>
          </div>
        </section>
        <section>
          <h2>Tony sandboxes (${tonySites.length})</h2>
          <p>
            Everything under <code>${escapeHtml(TONY_SITES_ROOT)}</code> is automatically mounted at
            <code>https://node-1.h3.surf-thailand.com/tony/sites/&lt;folder&gt;/</code>.
          </p>
          <ul class="site-grid">
            ${sitesList}
          </ul>
        </section>
      </main>
      <script>
        const DEFAULT_STATIC_BUNDLES = ${JSON.stringify(bundleNames)};
        const restartBtn = document.getElementById('restartBtn');
        if (restartBtn) {
          restartBtn.addEventListener('click', async () => {
            if (restartBtn.disabled) return;
            const secret = window.prompt('Enter Tony deploy secret to restart the app');
            if (!secret) return;
            restartBtn.disabled = true;
            restartBtn.textContent = 'Restarting…';
            try {
              const res = await fetch('/api/app/restart', {
                method: 'POST',
                headers: {
                  'Content-Type': 'application/json',
                  'x-tony-secret': secret.trim()
                }
              });
              if (!res.ok) {
                const detail = await res.text();
                throw new Error(detail || res.status);
              }
              const data = await res.json();
              const extra = data.detail ? ': ' + data.detail : '';
              alert('Restart ' + (data.restarted ? 'succeeded' : 'failed') + extra);
            } catch (err) {
              const reason = (err && err.message) ? err.message : err;
              alert('Restart failed: ' + (err.message || err));
            } finally {
              restartBtn.disabled = false;
              restartBtn.textContent = 'Restart app';
            }
          });
        }

        const releaseInfoEl = document.getElementById('releaseInfo');
        const bundleGridEl = document.getElementById('bundleDiagnostics');
        const routeStackEl = document.getElementById('routeStack');
        const refreshBundlesBtn = document.getElementById('refreshBundles');
        const refreshRoutesBtn = document.getElementById('refreshRoutes');

        const safeJson = async (response) => {
          if (!response.ok) {
            const detail = await response.text();
            throw new Error(detail || response.statusText);
          }
          return response.json();
        };

        const renderRelease = (release) => {
          if (!release) {
            releaseInfoEl.textContent = 'No release payload found (payload.json).';
            return;
          }
          const rows = Object.entries(release)
            .map(([key, value]) => {
              const serialized = typeof value === 'object' ? JSON.stringify(value) : value;
              return '<strong>' + key + ':</strong> <span>' + serialized + '</span>';
            })
            .join('');
          releaseInfoEl.innerHTML = rows || 'Empty release payload.';
        };

        const renderBundles = (bundles = []) => {
          if (!bundles.length) {
            bundleGridEl.textContent = 'No bundle data available.';
            return;
          }
          bundleGridEl.innerHTML = bundles
            .map((bundle) => {
              const statusClass = bundle.exists ? 'ok' : 'warn';
              const statusLabel = bundle.exists ? 'present' : 'missing';
              const files = bundle.files || 0;
              const bytes = bundle.bytes || 0;
              const updated = bundle.updatedAt || 'n/a';
              return (
                '<article class="bundle-card">' +
                '<div class="status-pill ' + statusClass + '">' + bundle.name + ': ' + statusLabel + '</div>' +
                '<h3>' + bundle.name + '</h3>' +
                '<div class="stat">Files: ' + files + '</div>' +
                '<div class="stat">Bytes: ' + bytes + '</div>' +
                '<div class="stat">Updated: ' + updated + '</div>' +
                '</article>'
              );
            })
            .join('');
        };

        const renderRoutes = (stack = []) => {
          if (!stack.length) {
            routeStackEl.textContent = 'Route stack unavailable.';
            return;
          }
          const lines = stack.map((layer) => {
            const methods = Array.isArray(layer.methods) ? layer.methods.join(',') : '';
            const path = layer.path || '/';
            return layer.index + ' • [' + layer.type + '] ' + path + (methods ? ' ' + methods : '');
          });
          routeStackEl.textContent = lines.join('\n');
        };

        const refreshRelease = async () => {
          releaseInfoEl.textContent = 'Loading release payload…';
          try {
            const data = await safeJson(await fetch('/api/debug/release'));
            renderRelease(data?.release || null);
          } catch (error) {
            releaseInfoEl.textContent = 'Release debug failed: ' + error.message;
          }
        };

        const refreshBundles = async () => {
          bundleGridEl.textContent = 'Loading bundle stats…';
          try {
            const namesParam = encodeURIComponent(DEFAULT_STATIC_BUNDLES.join(','));
            const data = await safeJson(await fetch('/api/debug/static-bundles?names=' + namesParam));
            renderBundles(data?.bundles || []);
          } catch (error) {
            bundleGridEl.textContent = 'Bundle debug failed: ' + error.message;
          }
        };

        const refreshRoutes = async () => {
          routeStackEl.textContent = 'Loading routes…';
          try {
            const data = await safeJson(await fetch('/api/debug/routes'));
            renderRoutes(data?.stack || []);
          } catch (error) {
            routeStackEl.textContent = 'Route debug failed: ' + error.message;
          }
        };

        refreshRelease();
        refreshBundles();
        refreshRoutes();

        if (refreshBundlesBtn) {
          refreshBundlesBtn.addEventListener('click', refreshBundles);
        }
        if (refreshRoutesBtn) {
          refreshRoutesBtn.addEventListener('click', refreshRoutes);
        }
      </script>
    </body>
  </html>`;
    res.send(html);
  } catch (error) {
    console.error('[site-man] Failed to render Tony panel', error);
    res.status(500).send('Tony panel unavailable');
  }
});

app.post('/api/app/restart', async (req, res) => {
  if (!TONY_DEPLOY_SECRET) {
    return res.status(503).json({ error: 'restart_unconfigured' });
  }

  const provided = (req.get('x-tony-secret') || '').trim();
  if (provided !== TONY_DEPLOY_SECRET) {
    return res.status(401).json({ error: 'forbidden' });
  }

  try {
    const outcome = await restartNodeDomain();
    return res.json({ restarted: outcome.restarted, detail: outcome.reason || outcome.error || null });
  } catch (error) {
    console.error('[site-man] manual restart failed', error);
    return res.status(500).json({ error: 'restart_failed', detail: error.message || 'unknown_error' });
  }
});

app.post('/voice-chat', async (req, res) => {
  if (!ensureGlamaReady(res)) {
    return;
  }

  const message = typeof req.body?.message === 'string' ? req.body.message.trim() : '';
  const history = Array.isArray(req.body?.history) ? req.body.history : [];
  const temperature = typeof req.body?.temperature === 'number' ? req.body.temperature : undefined;
  if (!message) {
    return res.status(400).json({ error: 'message_required' });
  }

  const sanitizedHistory = history
    .map((entry) => {
      const role = typeof entry?.role === 'string' ? entry.role.trim().toLowerCase() : '';
      const content = typeof entry?.content === 'string' ? entry.content.trim() : '';
      if (!role || !content) return null;
      if (!['user', 'assistant', 'system'].includes(role)) return null;
      return { role, content };
    })
    .filter(Boolean)
    .slice(-12);

  const messages = [{ role: 'system', content: GLAMA_SYSTEM_PROMPT }, ...sanitizedHistory, { role: 'user', content: message }];

  try {
    const { text, data } = await callGlamaChatCompletion({ messages, temperature });
    if (!text) {
      return res.status(502).json({ error: 'empty_response' });
    }
    return res.json({ reply: text, usage: data?.usage ?? null, session: { id: data?.id ?? null } });
  } catch (error) {
    console.error('[site-man] voice-chat failed', error);
    return res.status(502).json({ error: error.message || 'glama_chat_failed' });
  }
});

app.get('/api/health', (req, res) => {
  res.json({
    status: 'ok',
    node: process.version,
    glamaReady: isGlamaReady(),
    glamaModel: GLAMA_MODEL_DEFAULT,
    timestamp: new Date().toISOString()
  });
});

app.get('/api/greeting', (req, res) => {
  const name = req.query.name || 'friend';
  res.json({ message: `Hello, ${name}! Welcome to node-1 sample site.` });
});

app.post('/hooks/deploy', async (req, res) => {
  if (!WEBHOOK_SECRET) {
    return res.status(503).json({ error: 'webhook_unconfigured' });
  }

  const signature = req.get('X-Hub-Signature-256');
  const event = req.get('X-GitHub-Event');

  if (!req.rawBody || !verifySignature(signature, req.rawBody)) {
    return res.status(401).json({ error: 'invalid_signature' });
  }

  if (event !== 'push') {
    return res.status(202).json({ status: 'ignored', detail: `event ${event}` });
  }

  try {
    runDeployScript().catch((err) => console.error('[site-sample] deploy script failed', err));
    res.status(202).json({ status: 'accepted' });
  } catch (error) {
    console.error('[site-sample] failed to trigger deploy', error);
    res.status(500).json({ error: 'deploy_failed' });
  }
});

app.use((req, res, next) => {
  res.status(404).sendFile(path.join(__dirname, '..', 'public', '404.html'));
});

app.use((err, req, res, next) => {
  console.error(err);
  res.status(500).json({ error: 'Internal Server Error' });
});

app.get('/api/talk/guidance', (_req, res) => {
  res.json({ guidance: TALK_GUIDANCE_DEFAULT });
});

app.get('/api/debug/static-bundles', async (req, res) => {
  try {
    const names = typeof req.query?.names === 'string'
      ? req.query.names.split(',').map((name) => name.trim()).filter(Boolean)
      : undefined;
    const bundles = await describeStaticBundles(names);
    res.json({ bundles });
  } catch (error) {
    console.error('[site-man] static bundles debug failed', error);
    res.status(500).json({ error: 'static_bundles_failed' });
  }
});

app.get('/api/debug/routes', (_req, res) => {
  try {
    const stack = describeRouteStack(app?._router?.stack || []);
    res.json({ stack });
  } catch (error) {
    console.error('[site-man] routes debug failed', error);
    res.status(500).json({ error: 'routes_debug_failed' });
  }
});

app.get('/api/debug/release', async (_req, res) => {
  try {
    const release = await readReleaseMetadata();
    res.json({ release });
  } catch (error) {
    res.status(500).json({ error: 'release_debug_failed' });
  }
});

app.use(express.static(PUBLIC_ROOT));

app.listen(PORT, () => {
  console.log(`Sample site listening on port ${PORT}`);
});

if (TALK_PORT !== PORT) {
  const talkApp = express();
  talkApp.use(talkRouter);
  talkApp.listen(TALK_PORT, () => {
    console.log(`Talk panel listening on port ${TALK_PORT}`);
  });
}
