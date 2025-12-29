const path = require('path');
const express = require('express');
const cors = require('cors');
const dotenv = require('dotenv');
const fetch = require('node-fetch');
const crypto = require('crypto');

dotenv.config({ path: path.join(__dirname, '..', '.env') });

const APP_NAME = 'mcp-agents';
const APP_VERSION = '0.1.0';
const PORT = Number(process.env.PORT || 8046);
const AGENTS_API_BASE = process.env.AGENTS_API_BASE || 'http://127.0.0.1:4060/api';
const DEFAULT_USER_ID = process.env.AGENTS_DEFAULT_USER || 'default';
const DEFAULT_LIMIT = Number(process.env.AGENTS_DEFAULT_LIMIT || 12);

const MCP_PROTOCOL_VERSION = '2024-11-05';
const mcpSessions = new Map(); // sessionId -> { createdAt, initializedAt }

const newSessionId = () => {
  if (typeof crypto.randomUUID === 'function') {
    return `stream-${crypto.randomUUID()}`;
  }
  return `stream-${Date.now()}-${Math.random().toString(16).slice(2)}`;
};

const TOOL_SCHEMAS = {
  fetch_sessions: {
    name: 'fetch_sessions',
    description: 'List the most recent agents panel sessions for a user.',
    input_schema: {
      type: 'object',
      properties: {
        user_id: { type: 'string', description: 'Workspace/user identifier (default: "default").' },
        limit: { type: 'integer', minimum: 1, maximum: 100, description: 'Number of sessions to return.' }
      }
    }
  },
  fetch_archives: {
    name: 'fetch_archives',
    description: 'List archived sessions for a user.',
    input_schema: {
      type: 'object',
      properties: {
        user_id: { type: 'string' },
        limit: { type: 'integer', minimum: 1, maximum: 50 }
      }
    }
  },
  observability_probe: {
    name: 'observability_probe',
    description: 'Run a lightweight observability sweep (agents health + registry).',
    input_schema: {
      type: 'object',
      properties: {
        include_registry: {
          type: 'boolean',
          description: 'If true, fetch /api/agents/registry in addition to /api/health.'
        }
      }
    }
  },
  relay_prompt: {
    name: 'relay_prompt',
    description:
      'Send a prompt to the underlying Agents API (e.g., Dever orchestration) and return the run metadata.',
    input_schema: {
      type: 'object',
      required: ['prompt'],
      properties: {
        prompt: {
          type: 'string',
          minLength: 1,
          description: 'User text to forward to the agents orchestrator.'
        },
        user_id: {
          type: 'string',
          description: 'Workspace/user identifier (default: "default").'
        },
        session_id: {
          type: 'string',
          description: 'Existing session to append to. If omitted, a new one is created.'
        },
        session_title: {
          type: 'string',
          description: 'Optional title used when creating a new session.'
        },
        session_metadata: {
          type: 'object',
          description: 'Additional metadata applied when creating a session.'
        },
        agents: {
          type: 'array',
          items: { type: 'string' },
          description: 'Optional list of agent labels to queue.'
        },
        history_limit: {
          type: 'integer',
          minimum: 1,
          maximum: 200,
          description: 'Maximum number of prior messages to include.'
        },
        attachments: {
          type: 'array',
          description: 'Attachment descriptors passed through to the Agents API.',
          items: {
            type: 'object',
            properties: {
              name: { type: 'string' },
              mime: { type: 'string' },
              url: { type: 'string' },
              id: { type: 'string' },
              size: { type: 'number' }
            },
            required: ['name']
          }
        },
        locale: {
          type: 'string',
          description: 'BCP-47 locale tag (default: en-US).'
        },
        metadata: {
          type: 'object',
          description: 'Arbitrary metadata stored alongside the user message.'
        }
      }
    }
  }
};

const normalizeLimit = (value, fallback, max) => {
  const parsed = Number(value);
  if (Number.isNaN(parsed) || parsed <= 0) {
    return fallback;
  }
  return Math.min(parsed, max);
};

const isPlainObject = (value) => typeof value === 'object' && value !== null && !Array.isArray(value);

const toStringArray = (value, { limit = 10 } = {}) => {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((entry) => String(entry || '').trim())
    .filter(Boolean)
    .slice(0, limit);
};

const sanitizeAttachments = (value, { limit = 10 } = {}) => {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((entry) => (isPlainObject(entry) ? entry : null))
    .filter(Boolean)
    .slice(0, limit)
    .map((entry) => {
      const name = typeof entry.name === 'string' ? entry.name.trim() : '';
      if (!name) {
        return null;
      }
      const sanitized = { name };
      if (typeof entry.mime === 'string' && entry.mime.trim()) {
        sanitized.mime = entry.mime.trim();
      }
      if (typeof entry.url === 'string' && entry.url.trim()) {
        sanitized.url = entry.url.trim();
      }
      if (typeof entry.id === 'string' && entry.id.trim()) {
        sanitized.id = entry.id.trim();
      }
      if (typeof entry.size === 'number' && Number.isFinite(entry.size)) {
        sanitized.size = entry.size;
      }
      return sanitized;
    })
    .filter(Boolean);
};

const MCP_SESSIONS = new Map();

const jsonRpcError = (id, code, message, data) => ({
  jsonrpc: '2.0',
  id: id ?? null,
  error: {
    code,
    message,
    ...(data ? { data } : {})
  }
});

const jsonRpcResult = (id, result) => ({
  jsonrpc: '2.0',
  id,
  result
});

const getSessionIdFromRequest = (req) => req.headers['mcp-session-id'] || req.headers['Mcp-Session-Id'];

const ensureInitializedSession = (req) => {
  const sessionId = getSessionIdFromRequest(req);
  if (!sessionId || typeof sessionId !== 'string') {
    return { ok: false, error: { code: -32001, message: 'Missing mcp-session-id' } };
  }
  const session = MCP_SESSIONS.get(sessionId);
  if (!session) {
    return {
      ok: false,
      error: { code: -32002, message: 'Unknown session. Call initialize first.' }
    };
  }
  return { ok: true, sessionId, session };
};

const clampHistoryLimit = (value, fallback = 20, max = 200) => {
  const parsed = Number(value);
  if (Number.isNaN(parsed) || parsed <= 0) {
    return fallback;
  }
  return Math.min(parsed, max);
};

const fetchJson = async (url, options = {}) => {
  const response = await fetch(url, {
    headers: {
      'Content-Type': 'application/json',
      ...(options.headers || {})
    },
    ...options
  });
  if (!response.ok) {
    const text = await response.text();
    const error = new Error(`Request failed (${response.status}): ${text || 'no body'}`);
    error.status = response.status;
    throw error;
  }
  if (response.status === 204) {
    return null;
  }
  return response.json();
};

const buildUserBase = (userId) =>
  `${AGENTS_API_BASE}/users/${encodeURIComponent(userId || DEFAULT_USER_ID)}`;

const buildSessionUrl = (userId, sessionId, suffix = '') => {
  const base = `${buildUserBase(userId)}/sessions/${encodeURIComponent(sessionId)}`;
  return suffix ? `${base}/${suffix}` : base;
};

const ensureSession = async (userId, { sessionId, sessionTitle, sessionMetadata } = {}) => {
  const metadata = isPlainObject(sessionMetadata) ? { ...sessionMetadata } : {};
  const title = typeof sessionTitle === 'string' ? sessionTitle.trim() : '';
  if (title) {
    metadata.title = title;
    if (metadata.autoTitle === undefined) {
      metadata.autoTitle = false;
    }
  }

  if (sessionId) {
    if (Object.keys(metadata).length) {
      await fetchJson(buildSessionUrl(userId, sessionId), {
        method: 'PATCH',
        body: JSON.stringify({ metadata })
      });
    }
    return sessionId;
  }

  const payload = Object.keys(metadata).length ? { metadata } : {};
  const response = await fetchJson(`${buildUserBase(userId)}/sessions`, {
    method: 'POST',
    body: JSON.stringify(payload)
  });
  const createdId = response?.session?.id;
  if (!createdId) {
    throw new Error('Agents API did not return a session id');
  }
  return createdId;
};

const fetchSessions = async (args = {}) => {
  const userId = (args.user_id || DEFAULT_USER_ID).trim() || DEFAULT_USER_ID;
  const limit = normalizeLimit(args.limit, DEFAULT_LIMIT, 100);
  const url = `${buildUserBase(userId)}/sessions?limit=${limit}`;
  const payload = await fetchJson(url);
  return {
    user_id: userId,
    limit,
    sessions: payload?.sessions || []
  };
};

const fetchArchives = async (args = {}) => {
  const userId = (args.user_id || DEFAULT_USER_ID).trim() || DEFAULT_USER_ID;
  const limit = normalizeLimit(args.limit, Math.min(DEFAULT_LIMIT, 10), 50);
  const url = `${buildUserBase(userId)}/archives?limit=${limit}`;
  const payload = await fetchJson(url);
  return {
    user_id: userId,
    limit,
    archives: payload?.archives || []
  };
};

const observabilityProbe = async (args = {}) => {
  const results = {};
  try {
    results.health = await fetchJson(`${AGENTS_API_BASE.replace(/\/api$/, '')}/api/health`);
  } catch (error) {
    results.health = { status: 'error', detail: error.message };
  }

  if (args.include_registry) {
    try {
      results.registry = await fetchJson(`${AGENTS_API_BASE}/agents/registry`);
    } catch (error) {
      results.registry = { status: 'error', detail: error.message };
    }
  }

  return results;
};

const relayPrompt = async (args = {}) => {
  const prompt = typeof args.prompt === 'string' ? args.prompt.trim() : '';
  if (!prompt) {
    throw new Error('prompt is required');
  }

  const userId = (args.user_id || DEFAULT_USER_ID).trim() || DEFAULT_USER_ID;
  const locale = typeof args.locale === 'string' && args.locale.trim() ? args.locale.trim() : 'en-US';
  const historyLimit = clampHistoryLimit(args.history_limit ?? args.historyLimit);
  const agents = toStringArray(args.agents, { limit: 12 });
  const attachments = sanitizeAttachments(args.attachments, { limit: 10 });
  const metadata = isPlainObject(args.metadata) ? args.metadata : undefined;
  const sessionMetadata = isPlainObject(args.session_metadata) ? args.session_metadata : undefined;
  const sessionTitle = typeof args.session_title === 'string' ? args.session_title.trim() : '';
  const sessionId = await ensureSession(userId, {
    sessionId: typeof args.session_id === 'string' ? args.session_id.trim() : '',
    sessionTitle,
    sessionMetadata
  });

  const body = {
    prompt,
    agents,
    historyLimit,
    attachments,
    locale
  };

  if (metadata) {
    body.metadata = metadata;
  }

  const response = await fetchJson(buildSessionUrl(userId, sessionId, 'messages'), {
    method: 'POST',
    body: JSON.stringify(body)
  });

  return {
    user_id: userId,
    session_id: response?.sessionId || sessionId,
    run_id: response?.runId,
    status: response?.status || 'accepted',
    queued_agents: response?.queuedAgents || agents,
    locale,
    history_limit: historyLimit,
    attachments_count: attachments.length
  };
};

const TOOL_HANDLERS = {
  fetch_sessions: fetchSessions,
  fetch_archives: fetchArchives,
  observability_probe: observabilityProbe,
  relay_prompt: relayPrompt
};

const mcpToolList = () =>
  Object.values(TOOL_SCHEMAS).map((tool) => ({
    name: tool.name,
    description: tool.description,
    inputSchema: tool.input_schema
  }));

const mcpJsonError = (id, code, message) => ({
  jsonrpc: '2.0',
  id: id ?? null,
  error: {
    code,
    message
  }
});

const mcpJsonResult = (id, result) => ({
  jsonrpc: '2.0',
  id,
  result
});

const mcpTextContent = (value) => {
  if (typeof value === 'string') {
    return value;
  }
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
};

const app = express();
app.use(cors());
app.use(express.json({ limit: process.env.JSON_BODY_LIMIT || '1mb' }));

app.post('/mcp', async (req, res) => {
  const payload = req.body;
  const id = payload?.id;
  const method = payload?.method;

  if (!payload || payload.jsonrpc !== '2.0' || typeof method !== 'string') {
    return res.json(jsonRpcError(id, -32600, 'Invalid Request'));
  }

  if (method === 'initialize') {
    const sessionId = getSessionIdFromRequest(req);
    if (!sessionId || typeof sessionId !== 'string') {
      return res.json(jsonRpcError(id, -32001, 'Missing mcp-session-id'));
    }
    MCP_SESSIONS.set(sessionId, { initialized: false, createdAt: Date.now() });
    return res.json(
      jsonRpcResult(id, {
        protocolVersion: payload?.params?.protocolVersion || '2024-11-05',
        serverInfo: { name: APP_NAME, version: APP_VERSION },
        capabilities: { tools: {} }
      })
    );
  }

  if (method === 'notifications/initialized') {
    const ensured = ensureInitializedSession(req);
    if (!ensured.ok) {
      return res.json(jsonRpcError(id, ensured.error.code, ensured.error.message));
    }
    ensured.session.initialized = true;
    return res.json({ jsonrpc: '2.0', id: id ?? null, result: null });
  }

  const ensured = ensureInitializedSession(req);
  if (!ensured.ok) {
    return res.json(jsonRpcError(id, ensured.error.code, ensured.error.message));
  }
  if (!ensured.session.initialized) {
    return res.json(jsonRpcError(id, -32003, 'Server not initialized'));
  }

  if (method === 'tools/list') {
    return res.json(
      jsonRpcResult(id, {
        tools: Object.values(TOOL_SCHEMAS).map(({ name, description, input_schema }) => ({
          name,
          description,
          inputSchema: input_schema
        }))
      })
    );
  }

  if (method === 'tools/call') {
    const toolName = payload?.params?.name;
    const args = payload?.params?.arguments || {};
    if (!toolName || typeof toolName !== 'string') {
      return res.json(jsonRpcError(id, -32602, 'params.name is required'));
    }
    const handler = TOOL_HANDLERS[toolName];
    if (!handler) {
      return res.json(jsonRpcError(id, -32601, `Unknown tool '${toolName}'`));
    }
    try {
      const result = await handler(args);
      return res.json(
        jsonRpcResult(id, {
          content: [{ type: 'text', text: JSON.stringify(result) }]
        })
      );
    } catch (error) {
      console.error('[mcp-agents] mcp error', error);
      return res.json(jsonRpcError(id, -32000, error.message || 'agents_error'));
    }
  }

  return res.json(jsonRpcError(id, -32601, `Method '${method}' not found`));
});

app.get('/health', async (_req, res) => {
  const out = { status: 'ok', agents_api_base: AGENTS_API_BASE };
  try {
    const data = await fetchJson(`${AGENTS_API_BASE.replace(/\/api$/, '')}/api/health`);
    out.agents = data;
    out.upstream_ok = true;
  } catch (error) {
    out.agents = { status: 'error', detail: error.message };
    out.upstream_ok = false;
  }
  // Always 200 so container healthcheck reflects service health, not upstream dependency health.
  res.json(out);
});

app.post('/mcp', async (req, res) => {
  const accept = String(req.headers.accept || '');
  if (!accept.includes('application/json') || !accept.includes('text/event-stream')) {
    return res
      .status(406)
      .json(mcpJsonError(null, -32000, 'Not Acceptable: Client must accept both application/json and text/event-stream'));
  }

  const payload = req.body || {};
  const id = payload.id;
  const method = payload.method;
  const params = payload.params || {};

  const sessionIdHeader = req.headers['mcp-session-id'];
  const sessionId = typeof sessionIdHeader === 'string' ? sessionIdHeader : Array.isArray(sessionIdHeader) ? sessionIdHeader[0] : null;

  if (method === 'initialize') {
    const newId = newSessionId();
    mcpSessions.set(newId, { createdAt: new Date().toISOString(), initializedAt: null });
    res.setHeader('mcp-session-id', newId);
    return res.json(
      mcpJsonResult(id ?? null, {
        protocolVersion: MCP_PROTOCOL_VERSION,
        capabilities: {
          tools: { listChanged: true },
          resources: { listChanged: false },
          prompts: { listChanged: false },
          logging: {}
        },
        serverInfo: {
          name: APP_NAME,
          version: APP_VERSION
        }
      })
    );
  }

  if (!sessionId || !mcpSessions.has(sessionId)) {
    return res.status(400).json(mcpJsonError(id ?? null, -32001, 'Missing mcp-session-id'));
  }

  if (method === 'notifications/initialized') {
    const session = mcpSessions.get(sessionId);
    session.initializedAt = session.initializedAt || new Date().toISOString();
    mcpSessions.set(sessionId, session);
    return res.json({});
  }

  if (method === 'tools/list') {
    return res.json(mcpJsonResult(id ?? null, { tools: mcpToolList() }));
  }

  if (method === 'tools/call') {
    const toolName = params.name;
    const args = params.arguments || {};
    if (!toolName || typeof toolName !== 'string') {
      return res.status(400).json(mcpJsonError(id ?? null, -32602, 'Missing params.name'));
    }
    const handler = TOOL_HANDLERS[toolName];
    if (!handler) {
      return res.status(404).json(mcpJsonError(id ?? null, -32601, `Unknown tool '${toolName}'`));
    }
    try {
      const result = await handler(args);
      return res.json(
        mcpJsonResult(id ?? null, {
          content: [{ type: 'text', text: mcpTextContent(result) }]
        })
      );
    } catch (error) {
      console.error(`[${APP_NAME}] mcp tools/call error`, error);
      return res.status(500).json(mcpJsonError(id ?? null, -32000, error.message || 'tool_error'));
    }
  }

  return res.status(404).json(mcpJsonError(id ?? null, -32601, `Method '${method}' not found`));
});

app.post('/invoke', async (req, res) => {
  const { tool, arguments: args = {} } = req.body || {};
  if (!tool || typeof tool !== 'string') {
    return res.status(400).json({ error: 'tool is required' });
  }
  const handler = TOOL_HANDLERS[tool];
  if (!handler) {
    return res.status(404).json({ error: `Unknown tool '${tool}'` });
  }
  try {
    const result = await handler(args);
    return res.json(result);
  } catch (error) {
    console.error(`[${APP_NAME}] invoke error`, error);
    const status = error.status || 502;
    return res.status(status).json({ error: error.message || 'agents_error' });
  }
});

app.get('/.well-known/mcp.json', (_req, res) => {
  res.json({
    name: APP_NAME,
    version: APP_VERSION,
    description: 'Multi-agent observability MCP provider',
    capabilities: {
      tools: Object.values(TOOL_SCHEMAS)
    },
    metadata: {
      agents_api_base: AGENTS_API_BASE,
      default_user: DEFAULT_USER_ID
    }
  });
});

app.listen(PORT, () => {
  console.log(`[${APP_NAME}] listening on port ${PORT}`);
});
