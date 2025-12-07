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
