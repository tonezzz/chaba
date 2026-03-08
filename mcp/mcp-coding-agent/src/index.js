import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import dotenv from 'dotenv';
import express from 'express';
import cors from 'cors';
import crypto from 'node:crypto';
import { analyzeCode, fixBugs, reviewCode } from './codeAgent.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

dotenv.config({ path: path.resolve(__dirname, '..', '.env'), override: false });
dotenv.config({ path: path.resolve(__dirname, '..', '..', '..', '.env'), override: false });

const APP_NAME = 'mcp-coding-agent';
const APP_VERSION = '0.1.0';
const PORT = Number(process.env.MCP_CODING_AGENT_PORT || 8350);
const HOST = process.env.MCP_CODING_AGENT_HOST || '127.0.0.1';

const app = express();
app.use(cors());
app.use(express.json({ limit: process.env.MCP_CODING_AGENT_JSON_LIMIT || '4mb' }));

const coerceArgsObject = (value) => {
  if (!value) return {};
  if (typeof value === 'object') return value;
  if (typeof value === 'string') {
    const trimmed = value.trim();
    if (!trimmed) return {};
    try {
      const parsed = JSON.parse(trimmed);
      if (parsed && typeof parsed === 'object') return parsed;
    } catch {
      return {};
    }
  }
  return {};
};

const TOOLS = {
  analyze_code: {
    name: 'analyze_code',
    description:
      'Analyze a code snippet for bugs, security issues, performance problems, and style improvements. ' +
      'Returns a structured report with severity-ranked findings and an overall quality score.',
    input_schema: {
      type: 'object',
      required: ['code'],
      properties: {
        code: { type: 'string', description: 'The source code to analyze.' },
        language: {
          type: 'string',
          description: 'Programming language of the snippet (e.g. "javascript", "python"). Optional.'
        },
        question: {
          type: 'string',
          description: 'Optional focus question, e.g. "Are there any SQL injection risks?"'
        }
      }
    }
  },
  fix_bugs: {
    name: 'fix_bugs',
    description:
      'Fix bugs in a code snippet. Accepts an optional error message and bug description to guide the fix. ' +
      'Returns the corrected code, a list of changes made, and an explanation.',
    input_schema: {
      type: 'object',
      required: ['code'],
      properties: {
        code: { type: 'string', description: 'The source code containing the bug(s).' },
        language: { type: 'string', description: 'Programming language of the snippet. Optional.' },
        error_message: {
          type: 'string',
          description: 'Runtime error or stack trace to guide the fix. Optional.'
        },
        description: {
          type: 'string',
          description: 'Description of the observed bug or incorrect behavior. Optional.'
        }
      }
    }
  },
  review_code: {
    name: 'review_code',
    description:
      'Perform a thorough code review of a snippet. ' +
      'Returns a verdict (approve / approve_with_suggestions / request_changes), ' +
      'line-level comments, positives, and an overall quality score.',
    input_schema: {
      type: 'object',
      required: ['code'],
      properties: {
        code: { type: 'string', description: 'The source code to review.' },
        language: { type: 'string', description: 'Programming language of the snippet. Optional.' },
        context: {
          type: 'string',
          description:
            'Optional context about the code, e.g. "This is a REST API handler for user authentication."'
        }
      }
    }
  }
};

const MCP_SESSIONS = new Map();
const SSE_SESSIONS = new Map();

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

const writeSseEvent = (res, event, data) => {
  res.write(`event: ${event}\n`);
  res.write(`data: ${data}\n\n`);
};

const callTool = async (toolName, args) => {
  const env = process.env;
  switch (toolName) {
    case 'analyze_code': {
      if (!args.code || typeof args.code !== 'string') {
        throw Object.assign(new Error('code is required'), { rpcCode: -32602 });
      }
      return analyzeCode({
        code: args.code,
        language: args.language || null,
        question: args.question || null,
        env
      });
    }
    case 'fix_bugs': {
      if (!args.code || typeof args.code !== 'string') {
        throw Object.assign(new Error('code is required'), { rpcCode: -32602 });
      }
      return fixBugs({
        code: args.code,
        language: args.language || null,
        error_message: args.error_message || args.errorMessage || null,
        description: args.description || null,
        env
      });
    }
    case 'review_code': {
      if (!args.code || typeof args.code !== 'string') {
        throw Object.assign(new Error('code is required'), { rpcCode: -32602 });
      }
      return reviewCode({
        code: args.code,
        language: args.language || null,
        context: args.context || null,
        env
      });
    }
    default:
      throw Object.assign(new Error(`Tool '${toolName}' not implemented`), { rpcCode: -32601 });
  }
};

const handleMcpJsonRpc = async ({ payload, session }) => {
  const id = payload?.id;
  const method = payload?.method;

  if (!payload || payload.jsonrpc !== '2.0' || typeof method !== 'string') {
    return { type: 'response', payload: jsonRpcError(id, -32600, 'Invalid Request') };
  }

  if (method === 'initialize') {
    session.initialized = false;
    return {
      type: 'response',
      payload: jsonRpcResult(id, {
        protocolVersion: payload?.params?.protocolVersion || '2024-11-05',
        serverInfo: { name: APP_NAME, version: APP_VERSION },
        capabilities: { tools: {} }
      })
    };
  }

  if (method === 'notifications/initialized') {
    session.initialized = true;
    return { type: 'notification' };
  }

  if (!session.initialized) {
    return { type: 'response', payload: jsonRpcError(id, -32003, 'Server not initialized') };
  }

  if (method === 'tools/list') {
    return {
      type: 'response',
      payload: jsonRpcResult(id, {
        tools: Object.values(TOOLS).map(({ name, description, input_schema }) => ({
          name,
          description,
          inputSchema: input_schema
        }))
      })
    };
  }

  if (method === 'tools/call') {
    const toolName = payload?.params?.name;
    const args = coerceArgsObject(payload?.params?.arguments);
    if (!toolName || typeof toolName !== 'string') {
      return { type: 'response', payload: jsonRpcError(id, -32602, 'params.name is required') };
    }
    if (!TOOLS[toolName]) {
      return { type: 'response', payload: jsonRpcError(id, -32601, `Unknown tool '${toolName}'`) };
    }

    try {
      const result = await callTool(toolName, args);
      return {
        type: 'response',
        payload: jsonRpcResult(id, {
          content: [{ type: 'text', text: JSON.stringify(result) }]
        })
      };
    } catch (err) {
      const code = err.rpcCode || -32000;
      return { type: 'response', payload: jsonRpcError(id, code, err.message || 'internal_error') };
    }
  }

  return { type: 'response', payload: jsonRpcError(id, -32601, `Method '${method}' not found`) };
};

const getSessionIdFromRequest = (req) =>
  req.headers['mcp-session-id'] || req.headers['Mcp-Session-Id'] || req.get?.('mcp-session-id');

const ensureInitializedSession = (req) => {
  const sessionId = getSessionIdFromRequest(req);
  if (!sessionId || typeof sessionId !== 'string') {
    return { ok: false, error: { code: -32001, message: 'Missing mcp-session-id' } };
  }
  const session = MCP_SESSIONS.get(sessionId);
  if (!session) {
    return { ok: false, error: { code: -32002, message: 'Unknown session. Call initialize first.' } };
  }
  if (!session.initialized) {
    return { ok: false, error: { code: -32003, message: 'Server not initialized' } };
  }
  return { ok: true, sessionId, session };
};

app.get('/health', (_req, res) => {
  res.json({
    status: 'ok',
    service: APP_NAME,
    version: APP_VERSION,
    tools: Object.keys(TOOLS),
    timestamp: new Date().toISOString()
  });
});

app.get('/.well-known/mcp.json', (_req, res) => {
  res.json({
    name: APP_NAME,
    version: APP_VERSION,
    description: 'MCP coding agent: analyze, fix, and review source code with LLM assistance.',
    capabilities: {
      tools: Object.values(TOOLS).map(({ name, description, input_schema }) => ({
        name,
        description,
        input_schema
      }))
    }
  });
});

const handleSse = (req, res) => {
  const sessionId = crypto.randomUUID();
  const session = { initialized: false, createdAt: Date.now() };
  SSE_SESSIONS.set(sessionId, { session, res });

  res.status(200);
  res.setHeader('Content-Type', 'text/event-stream');
  res.setHeader('Cache-Control', 'no-cache');
  res.setHeader('Connection', 'keep-alive');
  res.setHeader('X-Accel-Buffering', 'no');
  res.flushHeaders?.();

  writeSseEvent(res, 'endpoint', `/messages?session_id=${encodeURIComponent(sessionId)}`);

  const heartbeatMs = Number(process.env.MCP_CODING_AGENT_SSE_HEARTBEAT_MS || 15000);
  const heartbeat = setInterval(() => {
    if (res.writableEnded) return;
    res.write(': ping\n\n');
  }, heartbeatMs);

  req.on('close', () => {
    clearInterval(heartbeat);
    SSE_SESSIONS.delete(sessionId);
  });
};

app.get('/sse', handleSse);

app.get('/', (req, res, next) => {
  const accept = req.headers?.accept || '';
  if (typeof accept === 'string' && accept.includes('text/event-stream')) {
    return handleSse(req, res);
  }
  return next();
});

app.post('/messages', async (req, res) => {
  const sessionId = req.query?.session_id;
  if (!sessionId || typeof sessionId !== 'string') {
    return res.status(400).json({ error: 'session_id is required' });
  }
  const entry = SSE_SESSIONS.get(sessionId);
  if (!entry) {
    return res.status(404).json({ error: 'Unknown session' });
  }

  try {
    const result = await handleMcpJsonRpc({ payload: req.body, session: entry.session, sessionId });
    if (result.type === 'response') {
      writeSseEvent(entry.res, 'message', JSON.stringify(result.payload));
      return res.status(202).json({ ok: true });
    }
    return res.status(204).end();
  } catch (err) {
    console.error(`[${APP_NAME}] messages error`, err);
    writeSseEvent(entry.res, 'message', JSON.stringify(jsonRpcError(req.body?.id, -32000, err.message || 'internal_error')));
    return res.status(202).json({ ok: false });
  }
});

app.post('/mcp', async (req, res) => {
  const payload = req.body;
  const id = payload?.id;
  const method = payload?.method;

  if (!payload || payload.jsonrpc !== '2.0' || typeof method !== 'string') {
    return res.status(400).json(jsonRpcError(id, -32600, 'Invalid Request'));
  }

  try {
    if (method === 'initialize') {
      const sessionId = crypto.randomUUID();
      MCP_SESSIONS.set(sessionId, { initialized: false, createdAt: Date.now() });
      res.setHeader('mcp-session-id', sessionId);
      return res.json(
        jsonRpcResult(id, {
          protocolVersion: payload?.params?.protocolVersion || '2024-11-05',
          serverInfo: { name: APP_NAME, version: APP_VERSION },
          capabilities: { tools: {} }
        })
      );
    }

    if (method === 'notifications/initialized') {
      const sessionId = getSessionIdFromRequest(req);
      if (!sessionId || typeof sessionId !== 'string') {
        return res.status(400).json(jsonRpcError(id, -32001, 'Missing mcp-session-id'));
      }
      const session = MCP_SESSIONS.get(sessionId);
      if (!session) {
        return res.status(400).json(jsonRpcError(id, -32002, 'Unknown session'));
      }
      session.initialized = true;
      return res.status(204).end();
    }

    if (method === 'tools/list') {
      const check = ensureInitializedSession(req);
      if (!check.ok) {
        return res.status(400).json(jsonRpcError(id, check.error.code, check.error.message));
      }
      return res.json(
        jsonRpcResult(id, {
          tools: Object.values(TOOLS).map(({ name, description, input_schema }) => ({
            name,
            description,
            inputSchema: input_schema
          }))
        })
      );
    }

    if (method === 'tools/call') {
      const check = ensureInitializedSession(req);
      if (!check.ok) {
        return res.status(400).json(jsonRpcError(id, check.error.code, check.error.message));
      }

      const toolName = payload?.params?.name;
      const args = coerceArgsObject(payload?.params?.arguments);
      if (!toolName || typeof toolName !== 'string') {
        return res.status(400).json(jsonRpcError(id, -32602, 'params.name is required'));
      }
      if (!TOOLS[toolName]) {
        return res.status(404).json(jsonRpcError(id, -32601, `Unknown tool '${toolName}'`));
      }

      try {
        const result = await callTool(toolName, args);
        return res.json(jsonRpcResult(id, { content: [{ type: 'text', text: JSON.stringify(result) }] }));
      } catch (err) {
        const code = err.rpcCode || -32000;
        return res.status(err.rpcCode === -32602 ? 400 : 502).json(jsonRpcError(id, code, err.message || 'internal_error'));
      }
    }

    return res.status(404).json(jsonRpcError(id, -32601, `Method '${method}' not found`));
  } catch (err) {
    console.error(`[${APP_NAME}] mcp error`, err);
    return res.status(502).json(jsonRpcError(id, -32000, err.message || 'internal_error'));
  }
});

app.post('/invoke', async (req, res) => {
  const { tool, arguments: argumentsField, args: argsField } = req.body || {};
  const args = coerceArgsObject(argumentsField ?? argsField);
  if (!tool || typeof tool !== 'string') {
    return res.status(400).json({ error: 'tool is required' });
  }
  if (!TOOLS[tool]) {
    return res.status(404).json({ error: `Unknown tool '${tool}'` });
  }

  try {
    const result = await callTool(tool, args);
    return res.json(result);
  } catch (err) {
    const isClientError = err.rpcCode === -32602 || err.rpcCode === -32601;
    if (!isClientError) console.error(`[${APP_NAME}] invoke error`, err);
    return res.status(isClientError ? (err.rpcCode === -32602 ? 400 : 404) : 502).json({ error: err.message || 'tool_failed' });
  }
});

app.listen(PORT, HOST, () => {
  console.log(`[${APP_NAME}] listening on ${HOST}:${PORT}`);
});
