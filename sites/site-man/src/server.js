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
const PORT = process.env.PORT || 3000;
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
const DEPLOY_SCRIPT =
  process.env.DEPLOY_SCRIPT || path.resolve(__dirname, '..', '..', '..', 'scripts', 'pull-node-1.sh');
const TONY_SITES_ROOT = path.resolve(__dirname, '..', '..', 'tony', 'sites');
const AGENTS_ROOT = path.resolve(__dirname, '..', 'agents');
const AGENT_REGISTRY_PATH = path.join(AGENTS_ROOT, 'registry.json');

const sessionStore = new Map();

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

const createSessionRecord = ({ agents, metadata }) => {
  const now = new Date().toISOString();
  const session = {
    id: generateId(),
    agents,
    metadata: metadata || null,
    createdAt: now,
    updatedAt: now,
    messages: []
  };
  sessionStore.set(session.id, session);
  return session;
};

const appendSessionMessage = (sessionId, message) => {
  const session = sessionStore.get(sessionId);
  if (!session) {
    return null;
  }
  session.messages.push(message);
  session.updatedAt = message.createdAt;
  return message;
};

const DEFAULT_AGENT_PROMPT = 'You are a helpful Surf Thailand assistant. Respond with concise, actionable information.';

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

const writeTonySiteFiles = async ({ siteSlug, files, clearExisting = false }) => {
  if (!siteSlug) {
    throw new Error('site_missing');
  }
  if (!Array.isArray(files) || !files.length) {
    throw new Error('files_missing');
  }

  const siteDir = path.join(TONY_SITES_ROOT, siteSlug);
  if (clearExisting) {
    await fs.rm(siteDir, { recursive: true, force: true });
  }
  await fs.mkdir(siteDir, { recursive: true });

  let written = 0;
  const details = [];

  for (const file of files) {
    const relativePath = normalizeRelativePath(file?.path || '');
    if (!relativePath || relativePath.includes('..')) {
      throw new Error(`invalid_path_${file?.path ?? ''}`);
    }

    const targetPath = path.join(siteDir, relativePath);
    if (!isWithinPath(siteDir, targetPath)) {
      throw new Error(`path_escape_${relativePath}`);
    }

    const encoding = file?.encoding === 'base64' ? 'base64' : 'utf8';
    const contents = typeof file?.contents === 'string' ? file.contents : '';
    const buffer = encoding === 'base64' ? Buffer.from(contents, 'base64') : Buffer.from(contents, 'utf8');

    await fs.mkdir(path.dirname(targetPath), { recursive: true });
    await fs.writeFile(targetPath, buffer);
    written += 1;
    details.push({ path: relativePath, bytes: buffer.length });
  }

  return { siteDir, written, details };
};

app.use(morgan('dev'));
app.use(express.json({ verify: rawBodyBuffer }));
app.use(express.static(path.join(__dirname, '..', 'public')));

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

app.get('/chat', (_req, res) => {
  res.sendFile(path.join(__dirname, '..', 'public', 'index.html'));
});

app.get('/api/agents', async (_req, res) => {
  try {
    const agents = await describeAgents();
    res.json({ agents });
  } catch (error) {
    console.error('[site-man] list agents failed', error);
    res.status(500).json({ error: 'agents_list_failed' });
  }
});

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

  const message = {
    id: generateId(),
    role,
    content,
    agentTargets: agentTargets && agentTargets.length ? agentTargets : null,
    createdAt: new Date().toISOString()
  };

  appendSessionMessage(session.id, message);
  return res.status(201).json({ message });
});

app.post('/api/sessions/:sessionId/run', async (req, res) => {
  if (!ensureGlamaReady(res)) {
    return;
  }

  const session = sessionStore.get(req.params.sessionId);
  if (!session) {
    return res.status(404).json({ error: 'session_not_found' });
  }

  const requested = Array.isArray(req.body?.agents)
    ? [...new Set(req.body.agents.map((id) => (id || '').toString().trim()).filter(Boolean))]
    : null;

  const targets = (requested && requested.length ? requested : session.agents).filter((id) => session.agents.includes(id));
  if (!targets.length) {
    return res.status(400).json({ error: 'agents_required' });
  }

  try {
    const responses = await Promise.all(targets.map((agentId) => runAgentResponse({ session, agentId }))); 
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

const readTonySites = async () => {
  try {
    const entries = await fs.readdir(TONY_SITES_ROOT, { withFileTypes: true });
    const folders = entries.filter((entry) => entry.isDirectory());
    const sites = await Promise.all(
      folders.map(async (dir) => {
        const sitePath = path.join(TONY_SITES_ROOT, dir.name);
        const indexPath = path.join(sitePath, 'index.html');
        let hasIndex = false;
        try {
          await fs.access(indexPath);
          hasIndex = true;
        } catch {
          hasIndex = false;
        }
        return {
          name: dir.name,
          label: formatSiteLabel(dir.name),
          url: `/tony/sites/${encodeURIComponent(dir.name)}/`,
          filesystemPath: sitePath,
          hasIndex
        };
      })
    );
    return sites.sort((a, b) => a.label.localeCompare(b.label));
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
            <div class="path">${escapeHtml(site.filesystemPath)}</div>
          </li>`
          )
          .join('')
      : '<li class="site-card empty">No folders found yet. Add one under \n            <code>c:/chaba/sites/tony/sites</code> to have it mounted automatically.</li>';

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

app.post('/api/tony/deploy', async (req, res) => {
  if (!TONY_DEPLOY_SECRET) {
    return res.status(503).json({ error: 'tony_deploy_unconfigured' });
  }

  const providedSecret = (req.get('x-tony-secret') || '').trim();
  if (providedSecret !== TONY_DEPLOY_SECRET) {
    return res.status(401).json({ error: 'forbidden' });
  }

  const siteSlug = normalizeSiteSlug(req.body?.site || '');
  const files = Array.isArray(req.body?.files) ? req.body.files : [];
  const clearExisting = Boolean(req.body?.clear === true || req.body?.clear === 'true');

  if (!siteSlug) {
    return res.status(400).json({ error: 'site_required' });
  }
  if (!files.length) {
    return res.status(400).json({ error: 'files_required' });
  }

  try {
    const { written, details } = await writeTonySiteFiles({ siteSlug, files, clearExisting });
    const restartOutcome = await restartNodeDomain();
    return res.json({
      status: 'ok',
      site: siteSlug,
      filesWritten: written,
      cleared: clearExisting,
      restarted: restartOutcome.restarted,
      restartDetail: restartOutcome.reason || restartOutcome.error || null,
      deployedAt: new Date().toISOString(),
      details
    });
  } catch (error) {
    console.error('[site-man] Tony deploy failed', error);
    return res.status(500).json({ error: 'tony_deploy_failed', detail: error.message || 'unknown_error' });
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

app.listen(PORT, () => {
  console.log(`Sample site listening on port ${PORT}`);
});
