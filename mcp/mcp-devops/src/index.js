const normalizeBoolean = (value) => {
  if (value === true || value === false) {
    return value;
  }
  if (typeof value === 'string') {
    const lowered = value.trim().toLowerCase();
    if (lowered === 'true') return true;
    if (lowered === 'false') return false;
  }
  return Boolean(value);
};

import express from 'express';
import cors from 'cors';
import crypto from 'node:crypto';
import { config } from './config.js';
import { listWorkflowMetadata, findWorkflow } from './workflowCatalog.js';
import { executeWorkflow } from './executors.js';

const app = express();
app.use(cors());
app.use(express.json({ limit: process.env.MCP_DEVOPS_JSON_LIMIT || '1mb' }));

const TOOLS = {
  list_workflows: {
    name: 'list_workflows',
    description: 'List all preview/publish workflows with metadata and usage hints.',
    input_schema: {
      type: 'object',
      properties: {}
    }
  },
  run_workflow: {
    name: 'run_workflow',
    description: 'Execute a workflow by id. Supports dry-run to preview commands.',
    input_schema: {
      type: 'object',
      required: ['workflow_id'],
      properties: {
        workflow_id: { type: 'string', description: 'ID from list_workflows.' },
        dry_run: {
          type: 'boolean',
          description: 'If true, return the command that would run without executing it.'
        }
      }
    }
  }
};

const serializeLogs = (logs = []) =>
  logs.map((entry) => ({
    stream: entry.stream,
    message: entry.message
  }));

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

const handleMcpJsonRpc = async ({ payload, session, sessionId }) => {
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
        serverInfo: {
          name: 'mcp-devops',
          version: '0.1.0'
        },
        capabilities: {
          tools: {}
        }
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
    const args = payload?.params?.arguments || {};
    if (!toolName || typeof toolName !== 'string') {
      return { type: 'response', payload: jsonRpcError(id, -32602, 'params.name is required') };
    }
    if (!TOOLS[toolName]) {
      return { type: 'response', payload: jsonRpcError(id, -32601, `Unknown tool '${toolName}'`) };
    }

    switch (toolName) {
      case 'list_workflows': {
        return {
          type: 'response',
          payload: jsonRpcResult(id, {
            content: [
              {
                type: 'text',
                text: JSON.stringify({ workflows: listWorkflowMetadata() })
              }
            ]
          })
        };
      }
      case 'run_workflow': {
        const workflowId = args.workflow_id;
        if (!workflowId) {
          return { type: 'response', payload: jsonRpcError(id, -32602, 'workflow_id is required') };
        }
        const workflow = findWorkflow(workflowId);
        if (!workflow) {
          return {
            type: 'response',
            payload: jsonRpcError(id, -32601, `Workflow '${workflowId}' not found`)
          };
        }
        const dryRun = normalizeBoolean(args.dry_run);
        const result = await executeWorkflow(workflow, { dryRun });
        const response = {
          workflow_id: workflow.id,
          dry_run: dryRun || result.dryRun || false,
          exit_code: result.exitCode,
          duration_ms: result.durationMs,
          command: result.command || null,
          outputs: workflow.outputs || {},
          logs: serializeLogs(result.logs)
        };
        return {
          type: 'response',
          payload: jsonRpcResult(id, {
            content: [{ type: 'text', text: JSON.stringify(response) }]
          })
        };
      }
      default:
        return { type: 'response', payload: jsonRpcError(id, -32601, `Tool '${toolName}' not implemented`) };
    }
  }

  return { type: 'response', payload: jsonRpcError(id, -32601, `Method '${method}' not found`) };
};

const getSessionIdFromRequest = (req) =>
  req.headers['mcp-session-id'] || req.headers['Mcp-Session-Id'];

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
  if (!session.initialized) {
    return {
      ok: false,
      error: { code: -32003, message: 'Server not initialized' }
    };
  }
  return { ok: true, sessionId, session };
};

app.get('/health', (_req, res) => {
  res.json({
    status: 'ok',
    workflows: listWorkflowMetadata().length,
    timestamp: new Date().toISOString()
  });
});

app.get('/.well-known/mcp.json', (_req, res) => {
  res.json({
    name: 'mcp-devops',
    version: '0.1.0',
    description:
      'MCP provider for Chaba dev-host previews and production deploy workflows.',
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

  const heartbeatMs = Number(process.env.MCP_DEVOPS_SSE_HEARTBEAT_MS || 15000);
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
    const result = await handleMcpJsonRpc({
      payload: req.body,
      session: entry.session,
      sessionId
    });

    if (result.type === 'response') {
      const data = JSON.stringify(result.payload);
      writeSseEvent(entry.res, 'message', data);
      return res.status(202).json({ ok: true });
    }

    return res.status(204).end();
  } catch (err) {
    console.error('[mcp-devops] messages error', err);
    const data = JSON.stringify(jsonRpcError(req.body?.id, -32000, err.message || 'internal_error'));
    writeSseEvent(entry.res, 'message', data);
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
          serverInfo: {
            name: 'mcp-devops',
            version: '0.1.0'
          },
          capabilities: {
            tools: {}
          }
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
      const ok = ensureInitializedSession(req);
      if (!ok.ok) {
        return res.status(400).json(jsonRpcError(id, ok.error.code, ok.error.message));
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
      const ok = ensureInitializedSession(req);
      if (!ok.ok) {
        return res.status(400).json(jsonRpcError(id, ok.error.code, ok.error.message));
      }

      const toolName = payload?.params?.name;
      const args = payload?.params?.arguments || {};
      if (!toolName || typeof toolName !== 'string') {
        return res.status(400).json(jsonRpcError(id, -32602, 'params.name is required'));
      }
      if (!TOOLS[toolName]) {
        return res.status(404).json(jsonRpcError(id, -32601, `Unknown tool '${toolName}'`));
      }

      switch (toolName) {
        case 'list_workflows': {
          return res.json(
            jsonRpcResult(id, {
              content: [
                {
                  type: 'text',
                  text: JSON.stringify({ workflows: listWorkflowMetadata() })
                }
              ]
            })
          );
        }
        case 'run_workflow': {
          const workflowId = args.workflow_id;
          if (!workflowId) {
            return res.status(400).json(jsonRpcError(id, -32602, 'workflow_id is required'));
          }
          const workflow = findWorkflow(workflowId);
          if (!workflow) {
            return res.status(404).json(jsonRpcError(id, -32601, `Workflow '${workflowId}' not found`));
          }
          const dryRun = normalizeBoolean(args.dry_run);
          const result = await executeWorkflow(workflow, { dryRun });
          const response = {
            workflow_id: workflow.id,
            dry_run: dryRun || result.dryRun || false,
            exit_code: result.exitCode,
            duration_ms: result.durationMs,
            command: result.command || null,
            outputs: workflow.outputs || {},
            logs: serializeLogs(result.logs)
          };
          return res.json(
            jsonRpcResult(id, {
              content: [{ type: 'text', text: JSON.stringify(response) }]
            })
          );
        }
        default:
          return res.status(400).json(jsonRpcError(id, -32601, `Tool '${toolName}' not implemented`));
      }
    }

    return res.status(404).json(jsonRpcError(id, -32601, `Method '${method}' not found`));
  } catch (err) {
    console.error('[mcp-devops] mcp error', err);
    return res.status(502).json(jsonRpcError(id, -32000, err.message || 'internal_error'));
  }
});

app.post('/invoke', async (req, res) => {
  const { tool, arguments: args = {} } = req.body || {};
  if (!tool || typeof tool !== 'string') {
    return res.status(400).json({ error: 'tool is required' });
  }

  if (!TOOLS[tool]) {
    return res.status(404).json({ error: `Unknown tool '${tool}'` });
  }

  try {
    switch (tool) {
      case 'list_workflows': {
        return res.json({
          workflows: listWorkflowMetadata()
        });
      }
      case 'run_workflow': {
        const workflowId = args.workflow_id;
        if (!workflowId) {
          return res.status(400).json({ error: 'workflow_id is required' });
        }
        const workflow = findWorkflow(workflowId);
        if (!workflow) {
          return res.status(404).json({ error: `Workflow '${workflowId}' not found` });
        }
        const dryRun = normalizeBoolean(args.dry_run);
        const result = await executeWorkflow(workflow, { dryRun });
        return res.json({
          workflow_id: workflow.id,
          dry_run: dryRun || result.dryRun || false,
          exit_code: result.exitCode,
          duration_ms: result.durationMs,
          command: result.command || null,
          outputs: workflow.outputs || {},
          logs: serializeLogs(result.logs)
        });
      }
      default:
        return res.status(400).json({ error: `Tool '${tool}' not implemented` });
    }
  } catch (err) {
    console.error('[mcp-devops] invoke error', err);
    return res.status(502).json({
      error: err.message || 'workflow_failed'
    });
  }
});

app.listen(config.port, config.host, () => {
  console.log(`[mcp-devops] listening on ${config.host}:${config.port}`);
});
