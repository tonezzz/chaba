const path = require('path');
const fs = require('fs');
const express = require('express');
const cors = require('cors');
const dotenv = require('dotenv');
const { chromium, firefox, webkit } = require('playwright');
const { performance } = require('perf_hooks');
const crypto = require('crypto');

dotenv.config({ path: path.join(__dirname, '..', '.env') });

const APP_NAME = 'mcp-playwright';
const APP_VERSION = '0.1.0';
const PORT = Number(process.env.PORT || 8025);
const DEFAULT_BROWSER = (process.env.PLAYWRIGHT_BROWSER || 'chromium').toLowerCase();
const HEADLESS = (process.env.PLAYWRIGHT_HEADLESS || 'true').toLowerCase() !== 'false';
const DEFAULT_TIMEOUT = Number(process.env.PLAYWRIGHT_TIMEOUT_MS || 15000);
const SCENARIOS_DIR = process.env.PLAYWRIGHT_SCENARIOS_DIR || path.join(__dirname, 'scenarios');
const OUTPUT_DIR = process.env.PLAYWRIGHT_OUTPUT_DIR || path.join(__dirname, 'output');

const SUPPORTED_BROWSERS = new Set(['chromium', 'firefox', 'webkit']);

const MCP_PROTOCOL_VERSION = '2024-11-05';
const mcpSessions = new Map(); // sessionId -> { createdAt, initializedAt }

const newSessionId = () => {
  if (typeof crypto.randomUUID === 'function') {
    return `stream-${crypto.randomUUID()}`;
  }
  return `stream-${Date.now()}-${Math.random().toString(16).slice(2)}`;
};

const ensureDir = (dirPath) => {
  if (!fs.existsSync(dirPath)) {
    fs.mkdirSync(dirPath, { recursive: true });
  }
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

ensureDir(SCENARIOS_DIR);
ensureDir(OUTPUT_DIR);

const browserEngines = { chromium, firefox, webkit };

const pickBrowser = (name = DEFAULT_BROWSER) => {
  const normalized = String(name || DEFAULT_BROWSER).toLowerCase();
  if (!SUPPORTED_BROWSERS.has(normalized)) {
    throw new Error(`Unsupported browser '${name}'. Choose from chromium, firefox, webkit.`);
  }
  return normalized;
};

const launchContext = async ({ browserName, viewport }) => {
  const name = pickBrowser(browserName);
  const browser = await browserEngines[name].launch({ headless: HEADLESS });
  const context = await browser.newContext(
    viewport
      ? {
          viewport,
          deviceScaleFactor: viewport.deviceScaleFactor || 1
        }
      : {}
  );
  const page = await context.newPage();
  return { browser, context, page };
};

const closeContext = async ({ browser, context }) => {
  try {
    if (context) {
      await context.close();
    }
  } catch (err) {
    console.warn('[mcp-playwright] Failed closing context:', err.message);
  }
  if (browser) {
    await browser.close();
  }
};

const withPage = async (options, task) => {
  const session = await launchContext(options);
  try {
    return await task(session.page);
  } finally {
    await closeContext(session);
  }
};

const scenarioCache = new Map();

const loadScenario = (name) => {
  if (!name || typeof name !== 'string') {
    throw new Error('scenario name is required');
  }
  if (scenarioCache.has(name)) {
    return scenarioCache.get(name);
  }
  const filename = name.endsWith('.json') ? name : `${name}.json`;
  const fullPath = path.join(SCENARIOS_DIR, filename);
  if (!fs.existsSync(fullPath)) {
    throw new Error(`Scenario '${name}' not found in ${SCENARIOS_DIR}`);
  }
  const payload = JSON.parse(fs.readFileSync(fullPath, 'utf-8'));
  scenarioCache.set(name, payload);
  return payload;
};

const executeScenario = async (scenario, { browserName, timeout }) => {
  if (!Array.isArray(scenario?.actions) || !scenario.actions.length) {
    throw new Error('Scenario must include an actions array');
  }

  const outputs = [];
  await withPage({ browserName }, async (page) => {
    const start = performance.now();

    for (const action of scenario.actions) {
      const type = String(action?.type || '').toLowerCase();
      if (!type) {
        throw new Error('Scenario action is missing type');
      }
      switch (type) {
        case 'goto':
          await page.goto(action.url, {
            waitUntil: action.waitUntil || 'load',
            timeout: action.timeout || timeout || DEFAULT_TIMEOUT
          });
          break;
        case 'wait_for_selector':
          await page.waitForSelector(action.selector, {
            timeout: action.timeout || timeout || DEFAULT_TIMEOUT,
            state: action.state || 'visible'
          });
          break;
        case 'click':
          await page.click(action.selector, { timeout: action.timeout || timeout || DEFAULT_TIMEOUT });
          break;
        case 'fill':
          await page.fill(action.selector, action.value || '', {
            timeout: action.timeout || timeout || DEFAULT_TIMEOUT
          });
          break;
        case 'press':
          await page.press(action.selector, action.key, {
            timeout: action.timeout || timeout || DEFAULT_TIMEOUT
          });
          break;
        case 'delay':
          await page.waitForTimeout(Number(action.ms || action.duration || 500));
          break;
        case 'screenshot': {
          const fileName = action.file || `${Date.now()}-${Math.random().toString(36).slice(2)}.png`;
          const targetPath = path.join(OUTPUT_DIR, fileName);
          await page.screenshot({
            path: targetPath,
            fullPage: Boolean(action.fullPage ?? true),
            type: action.format === 'jpeg' ? 'jpeg' : 'png',
            quality: action.format === 'jpeg' ? Number(action.quality || 80) : undefined
          });
          outputs.push({
            type: 'file',
            path: targetPath,
            description: action.description || 'Scenario screenshot'
          });
          break;
        }
        default:
          throw new Error(`Unsupported scenario action '${action.type}'`);
      }
    }

    outputs.push({
      type: 'text',
      text: `Scenario '${scenario.name || 'unnamed'}' completed in ${Math.round(
        performance.now() - start
      )} ms`
    });
  });

  return outputs;
};

const captureScreenshot = async ({
  url,
  browser: browserName,
  fullPage = true,
  width = 1280,
  height = 720,
  format = 'png',
  waitUntil = 'load',
  waitForSelector,
  timeout
}) => {
  if (!url || typeof url !== 'string') {
    throw new Error('url is required');
  }
  const filename = `${Date.now()}-${Math.random().toString(36).slice(2)}.${format === 'jpeg' ? 'jpg' : 'png'}`;
  const targetPath = path.join(OUTPUT_DIR, filename);

  const pageResult = await withPage(
    {
      browserName,
      viewport: { width: Number(width) || 1280, height: Number(height) || 720 }
    },
    async (page) => {
      const plannedTimeout = timeout || DEFAULT_TIMEOUT;
      const navigationStart = performance.now();
      const response = await page.goto(url, { waitUntil, timeout: plannedTimeout });
      const timing = performance.now() - navigationStart;
      if (waitForSelector) {
        await page.waitForSelector(waitForSelector, { timeout: plannedTimeout });
      }
      await page.screenshot({
        path: targetPath,
        fullPage: Boolean(fullPage),
        type: format === 'jpeg' ? 'jpeg' : 'png',
        quality: format === 'jpeg' ? 80 : undefined
      });
      return {
        status: response?.status() ?? null,
        load_ms: Math.round(timing),
        url: response?.url() || url
      };
    }
  );

  return [
    {
      type: 'file',
      path: targetPath,
      description: `Screenshot of ${pageResult.url} (${pageResult.status})`
    },
    {
      type: 'text',
      text: `Navigation status ${pageResult.status}, load ${pageResult.load_ms} ms`
    }
  ];
};

const browserProbe = async ({ url, browser, timeout }) => {
  if (!url) {
    throw new Error('url is required');
  }
  const diagnostics = await withPage({ browserName: browser }, async (page) => {
    const metrics = { console: [], requests: [] };
    page.on('console', (msg) => metrics.console.push({ type: msg.type(), text: msg.text() }));
    page.on('requestfailed', (req) =>
      metrics.requests.push({ url: req.url(), failure: req.failure()?.errorText })
    );
    const start = performance.now();
    const response = await page.goto(url, { waitUntil: 'load', timeout: timeout || DEFAULT_TIMEOUT });
    const duration = Math.round(performance.now() - start);
    return {
      status: response?.status() ?? null,
      duration_ms: duration,
      final_url: response?.url() || url,
      console_events: metrics.console.slice(0, 20),
      failed_requests: metrics.requests.slice(0, 20)
    };
  });

  return [
    {
      type: 'text',
      text: JSON.stringify(diagnostics, null, 2)
    }
  ];
};

const TOOL_HANDLERS = {
  capture_screenshot: captureScreenshot,
  browser_probe: browserProbe,
  run_scenario: async (args = {}) => {
    const scenarioName = args.name || args.scenario;
    if (!scenarioName) {
      throw new Error('scenario name is required');
    }
    const scenario = loadScenario(scenarioName);
    if (args.overrides && typeof args.overrides === 'object') {
      const overrides = args.overrides;
      scenario.actions = scenario.actions.map((action) => {
        const next = { ...action };
        if (overrides.url && action.type?.toLowerCase() === 'goto') {
          next.url = overrides.url;
        }
        if (overrides.waitForSelector && action.type?.toLowerCase() === 'wait_for_selector') {
          next.selector = overrides.waitForSelector;
        }
        return next;
      });
    }
    return executeScenario(scenario, { browserName: args.browser, timeout: args.timeout });
  }
};

const TOOL_SCHEMAS = {
  capture_screenshot: {
    name: 'capture_screenshot',
    description: 'Navigate to a URL and capture a screenshot using Playwright.',
    input_schema: {
      type: 'object',
      required: ['url'],
      properties: {
        url: { type: 'string', format: 'uri' },
        browser: { type: 'string', enum: Array.from(SUPPORTED_BROWSERS) },
        fullPage: { type: 'boolean', default: true },
        width: { type: 'integer', minimum: 320, maximum: 2560 },
        height: { type: 'integer', minimum: 320, maximum: 1600 },
        format: { type: 'string', enum: ['png', 'jpeg'], default: 'png' },
        waitUntil: {
          type: 'string',
          enum: ['load', 'domcontentloaded', 'networkidle', 'commit'],
          default: 'load'
        },
        waitForSelector: { type: 'string' },
        timeout: { type: 'integer', minimum: 1000, maximum: 60000 }
      }
    }
  },
  browser_probe: {
    name: 'browser_probe',
    description: 'Load a URL and capture diagnostics (status, duration, console, request failures).',
    input_schema: {
      type: 'object',
      required: ['url'],
      properties: {
        url: { type: 'string', format: 'uri' },
        browser: { type: 'string', enum: Array.from(SUPPORTED_BROWSERS) },
        timeout: { type: 'integer', minimum: 1000, maximum: 60000 }
      }
    }
  },
  run_scenario: {
    name: 'run_scenario',
    description:
      'Execute a predefined scenario from the scenarios directory (click flows, waits, screenshots).',
    input_schema: {
      type: 'object',
      required: ['name'],
      properties: {
        name: { type: 'string', description: 'Scenario filename (without .json)' },
        browser: { type: 'string', enum: Array.from(SUPPORTED_BROWSERS) },
        timeout: { type: 'integer', minimum: 1000, maximum: 60000 },
        overrides: {
          type: 'object',
          description: 'Optional overrides (e.g., alternate URL).',
          properties: {
            url: { type: 'string', format: 'uri' }
          }
        }
      }
    }
  }
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

const app = express();
app.use(cors());
app.use(express.json({ limit: '500kb' }));

app.post('/mcp-legacy', async (req, res) => {
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
      const outputs = await handler(args);
      return res.json(jsonRpcResult(id, { content: outputs }));
    } catch (error) {
      console.error('[mcp-playwright] mcp error', error);
      return res.json(jsonRpcError(id, -32000, error.message || 'playwright_error'));
    }
  }

  return res.json(jsonRpcError(id, -32601, `Method '${method}' not found`));
});

app.get('/health', async (_req, res) => {
  try {
    pickBrowser(DEFAULT_BROWSER);
    const scenarios = fs.existsSync(SCENARIOS_DIR)
      ? fs.readdirSync(SCENARIOS_DIR).filter((file) => file.endsWith('.json'))
      : [];
    res.json({
      status: 'ok',
      headless: HEADLESS,
      scenarios,
      output_dir: OUTPUT_DIR
    });
  } catch (error) {
    res.status(500).json({ status: 'error', detail: error.message });
  }
});

app.post('/invoke', async (req, res) => {
  const { tool, arguments: args = {} } = req.body || {};
  if (!tool) {
    return res.status(400).json({ error: 'tool is required' });
  }
  const handler = TOOL_HANDLERS[tool];
  if (!handler) {
    return res.status(404).json({ error: `Unknown tool '${tool}'` });
  }
  try {
    const result = await handler(args);
    res.json({ outputs: result });
  } catch (error) {
    console.error('[mcp-playwright] invoke error', error);
    res.status(502).json({ error: error.message || 'playwright_error' });
  }
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

  const sessionIdHeader = req.headers['mcp-session-id'] || req.headers['Mcp-Session-Id'];
  const sessionId =
    typeof sessionIdHeader === 'string'
      ? sessionIdHeader
      : Array.isArray(sessionIdHeader)
        ? sessionIdHeader[0]
        : null;

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
      const outputs = await handler(args);
      return res.json(
        mcpJsonResult(id ?? null, {
          content: outputs
        })
      );
    } catch (error) {
      console.error('[mcp-playwright] mcp tools/call error', error);
      return res.status(500).json(mcpJsonError(id ?? null, -32000, error.message || 'playwright_error'));
    }
  }

  return res.status(404).json(mcpJsonError(id ?? null, -32601, `Method '${method}' not found`));
});

app.get('/.well-known/mcp.json', (_req, res) => {
  res.json({
    name: APP_NAME,
    version: APP_VERSION,
    description: 'Playwright-driven MCP provider for probes, screenshots, and scripted flows.',
    capabilities: {
      tools: Object.values(TOOL_SCHEMAS)
    },
    metadata: {
      default_browser: DEFAULT_BROWSER,
      headless: HEADLESS,
      scenarios_dir: SCENARIOS_DIR
    }
  });
});

app.listen(PORT, () => {
  console.log(`[mcp-playwright] listening on port ${PORT}`);
});
