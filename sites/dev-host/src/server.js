import fs from 'fs';
import path from 'path';
import express from 'express';
import morgan from 'morgan';
import dotenv from 'dotenv';
import { createProxyMiddleware } from 'http-proxy-middleware';
import { spawn } from 'child_process';
import { randomUUID } from 'crypto';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const app = express();
const PORT = process.env.PORT || 3000;
const loadEnv = () => {
  const candidates = [
    path.resolve(__dirname, '..', '.env.dev-host'),
    path.resolve(__dirname, '..', '.env'),
    path.resolve(__dirname, '../../.env.dev-host'),
    path.resolve(__dirname, '../../.env')
  ];
  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) {
      dotenv.config({ path: candidate });
      console.log(`[dev-host] Loaded environment from ${candidate}`);
      return;
    }
  }
  dotenv.config();
};

loadEnv();

const DEV_HOST_BASE_URL = (process.env.DEV_HOST_BASE_URL || 'http://dev-host:3100').replace(/\/+$/, '');
const DEV_HOST_PUBLISH_TOKEN = (process.env.DEV_HOST_PUBLISH_TOKEN || '').trim();
const GLAMA_PROXY_TARGET =
  (process.env.GLAMA_PROXY_TARGET ?? process.env.DEV_HOST_GLAMA_TARGET ?? 'http://127.0.0.1:4020').trim();
const AGENTS_PROXY_TARGET =
  (process.env.AGENTS_PROXY_TARGET ?? process.env.DEV_HOST_AGENTS_TARGET ?? 'http://127.0.0.1:4060').trim();
const DETECTS_PROXY_TARGET =
  (process.env.DETECTS_PROXY_TARGET ?? process.env.DEV_HOST_DETECTS_TARGET ?? 'http://localhost:4120').trim();
const VAJA_PROXY_TARGET = (process.env.VAJA_PROXY_TARGET || process.env.DEV_HOST_VAJA_TARGET || '').trim();
const MCP0_PROXY_TARGET =
  (process.env.MCP0_PROXY_TARGET ?? process.env.DEV_HOST_MCP0_TARGET ?? 'http://host.docker.internal:8310').trim();

const workspaceRoot = path.resolve(__dirname, '..', '..');

const resolveSitePath = (...segments) => {
  const direct = path.join(workspaceRoot, ...segments);
  if (fs.existsSync(direct)) {
    return direct;
  }
  const nested = path.join(workspaceRoot, 'sites', ...segments);
  if (fs.existsSync(nested)) {
    return nested;
  }
  return direct;
};

const testLandingRoot = resolveSitePath('a1-idc1', 'test');
const wwwRoot = resolveSitePath('a1-idc1', 'www');
const additionalStaticRoutes = [
  {
    basePath: '/test/chat',
    roots: [resolveSitePath('a1-idc1', 'test', 'chat')],
    spa: true
  },
  {
    basePath: '/test/agents',
    roots: [
      resolveSitePath('a1-idc1', 'test', 'agents'),
      resolveSitePath('a1-idc1', 'www', 'test', 'agents')
    ],
    spa: true,
    skipApiFallback: true
  },
  {
    basePath: '/test/detects',
    roots: [resolveSitePath('a1-idc1', 'test', 'detects')],
    spa: true
  },
  
];

const PROXY_CHECKS = [
  { id: 'glama', label: 'Glama chat', target: GLAMA_PROXY_TARGET, path: '/api/health' },
  { id: 'agents', label: 'Agents API', target: AGENTS_PROXY_TARGET, path: '/api/health' },
  { id: 'detects', label: 'Detects API', target: DETECTS_PROXY_TARGET, path: '/health' },
  { id: 'mcp0', label: 'MCP0 control', target: MCP0_PROXY_TARGET, path: '/health' }
];

const fetchWithTimeout = async (url, { timeout = 4000, ...options } = {}) => {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
};

const safeParseBody = async (response) => {
  const contentType = response.headers.get('content-type') || '';
  if (contentType.includes('application/json')) {
    return await response.json();
  }
  const text = await response.text();
  return text.length > 500 ? `${text.slice(0, 500)}…` : text;
};

const probeProxyTargets = async () =>
  Promise.all(
    PROXY_CHECKS.map(async (check) => {
      const result = {
        id: check.id,
        label: check.label,
        target: check.target,
        status: 'unconfigured',
        latencyMs: null
      };
      if (!check.target) {
        return result;
      }
      const started = Date.now();
      try {
        const base = check.target.replace(/\/+$/, '');
        const url = `${base}${check.path || ''}`;
        const response = await fetchWithTimeout(url, { timeout: check.timeoutMs || 4000 });
        result.latencyMs = Date.now() - started;
        result.httpStatus = response.status;
        if (response.ok) {
          result.status = 'ok';
          result.body = await safeParseBody(response);
        } else {
          result.status = 'error';
          result.error = `HTTP ${response.status}`;
          result.body = await safeParseBody(response);
        }
      } catch (error) {
        result.latencyMs = Date.now() - started;
        result.status = 'error';
        result.error = error.message;
      }
      return result;
    })
  );

const overallStatusFromProxies = (proxies) =>
  proxies.every((entry) => entry.status === 'ok' || entry.status === 'unconfigured') ? 'ok' : 'degraded';

const getSiteStatuses = () =>
  siteConfigs.map((site) => ({
    slug: site.slug,
    rootExists: fs.existsSync(site.root),
    label: site.label
  }));

const deployConfigs = {
  'a1-idc1': {
    script: path.join(workspaceRoot, 'scripts', 'deploy-a1-idc1.sh'),
    cwd: workspaceRoot,
    env: {
      SSH_KEY_PATH:
        process.env.A1_DEPLOY_SSH_KEY_PATH ||
        path.join(workspaceRoot, '.secrets', 'dev-host', '.ssh', 'chaba_ed25519')
    }
  }
};

const siteConfigs = [
  {
    slug: 'a1-idc1',
    label: 'A1 IDC1 preview',
    root: resolveSitePath('a1-idc1'),
    publicUrl: 'https://a1.idc1.surf-thailand.com'
  },
  {
    slug: 'idc1',
    label: 'IDC1 preview',
    root: resolveSitePath('idc1'),
    publicUrl: 'https://idc1.surf-thailand.com'
  }
];

const resolveStaticDirs = (siteRoot) => {
  const candidates = [
    path.join(siteRoot, 'public'),
    path.join(siteRoot, 'public-static'),
    path.join(siteRoot, 'test'),
    siteRoot
  ];
  return candidates.filter((dir, index, arr) => fs.existsSync(dir) && arr.indexOf(dir) === index);
};

const buildSiteRouter = (site) => {
  const router = express.Router();
  const staticDirs = resolveStaticDirs(site.root);

  if (!staticDirs.length) {
    router.use((_req, res) => {
      res.status(404).json({ error: 'site_root_missing', site: site.slug });
    });
    return router;
  }

  staticDirs.forEach((dir) => {
    router.use(express.static(dir, { fallthrough: true }));
  });

  router.get('/api/health', (_req, res) => {
    res.json({ site: site.slug, status: 'ok', timestamp: new Date().toISOString() });
  });

  router.use((req, res, next) => {
    const fallback = staticDirs
      .map((dir) => path.join(dir, 'index.html'))
      .find((candidate) => fs.existsSync(candidate));

    if (fallback) {
      return res.sendFile(fallback);
    }

    return next();
  });

  router.use((req, res) => {
    res.status(404).json({ error: 'not_found', site: site.slug, path: req.path });
  });

  return router;
};

app.use(morgan('dev'));

const mountTestStaticRoutes = () => {
  const testLandingRoot = resolveSitePath('a1-idc1', 'test');
  const landingExists = fs.existsSync(testLandingRoot);
  console.log('[dev-host] mounting /test static root', {
    testLandingRoot,
    landingExists
  });

  additionalStaticRoutes.forEach(({ basePath, roots, spa, skipApiFallback }) => {
    const router = express.Router();
    const resolvedRoots = roots.filter((dir) => fs.existsSync(dir));

    if (!resolvedRoots.length) {
      router.use((_req, res) => {
        res.status(404).json({ error: 'static_root_missing', basePath });
      });
    } else {
      if (skipApiFallback) {
        router.use((req, _res, next) => {
          const localPath = req.path || '';
          if (localPath.startsWith('/api') || localPath.startsWith('api')) {
            return next('route');
          }
          return next();
        });
      }
      resolvedRoots.forEach((dir) => router.use(express.static(dir, { fallthrough: true })));

      if (spa) {
        router.use((req, res, next) => {
          const localPath = req.path || '';
          if (skipApiFallback && (localPath.startsWith('/api') || localPath.startsWith('api'))) {
            return next();
          }
          const fallback = resolvedRoots
            .map((dir) => path.join(dir, 'index.html'))
            .find((candidate) => fs.existsSync(candidate));
          if (fallback) {
            return res.sendFile(fallback);
          }
          return next();
        });
      }
    }

    router.use((req, res) => {
      res.status(404).json({ error: 'not_found', basePath, path: req.path });
    });

    app.use(basePath, router);
  });

  const sendTestLanding = (req, res, next) => {
    const fallback = path.join(testLandingRoot, 'index.html');
    const exists = fs.existsSync(fallback);
    console.log('[dev-host] /test landing check', {
      url: req.originalUrl,
      fallback,
      exists
    });
    if (exists) {
      res.sendFile(fallback, (err) => {
        if (err) {
          console.error('[dev-host] /test landing sendFile error', err);
          return next(err);
        }
        console.log('[dev-host] /test landing served', req.originalUrl);
      });
      return;
    }
    console.warn('[dev-host] /test landing missing fallback', fallback);
    return next();
  };

  const testRouter = express.Router();
  testRouter.use(express.static(testLandingRoot, { fallthrough: true }));
  testRouter.get(['/', '/index.html', ''], sendTestLanding);
  app.use('/test', testRouter);
};

const mountWwwStaticRoutes = () => {
  const exists = fs.existsSync(wwwRoot);
  console.log('[dev-host] mounting /www static root', {
    wwwRoot,
    exists
  });

  if (!exists) {
    app.use('/www', (_req, res) => {
      res.status(404).json({ error: 'www_root_missing', path: '/www' });
    });
    return;
  }

  const router = express.Router();
  router.use(express.static(wwwRoot, { fallthrough: true }));
  router.use((req, res) => {
    res.status(404).json({ error: 'not_found', basePath: '/www', path: req.path });
  });

  app.use('/www', router);
};

const logRouteStack = () => {
  if (!app._router?.stack) {
    console.log('[dev-host] router stack unavailable');
    return;
  }
  const summary = app._router.stack
    .map((layer) => {
      if (layer.route?.path) {
        const methods = Object.keys(layer.route.methods || {}).join(',').toUpperCase();
        return `ROUTE ${methods || 'ALL'} ${layer.route.path}`;
      }
      if (layer.name === 'router' && layer.regexp) {
        return `MOUNT ${layer.regexp}`;
      }
      return `MIDDLEWARE ${layer.name || 'anonymous'}`;
    })
    .join('\n');
  console.log('[dev-host] route stack:\n' + summary);
};

const wireProxies = () => {
  app.use((req, _res, next) => {
    if (req.originalUrl.startsWith('/test')) {
      console.log('[dev-host] /test tap', req.method, req.originalUrl);
    }
    next();
  });

  const mountProxy = (mountPath, target, { id, pathRewrite }) => {
    if (!target) {
      app.use(mountPath, (_req, res) => {
        res.status(503).json({ error: 'proxy_unconfigured', id, mountPath });
      });
      return;
    }

    app.use(
      mountPath,
      createProxyMiddleware({
        target,
        changeOrigin: true,
        pathRewrite,
        onProxyReq: (proxyReq) => {
          proxyReq.setHeader('x-dev-host-proxy', id);
        },
        onError: (err, req, res) => {
          console.error(`[dev-host] ${mountPath} proxy error`, err.message);
          if (!res.headersSent) {
            res.status(502).json({ error: 'proxy_error', detail: err.message });
          }
        }
      })
    );
  };

  mountProxy('/test/agents/api', AGENTS_PROXY_TARGET, {
    id: 'test-agents-api',
    pathRewrite: (path) => path.replace(/^\/test\/agents\/api/i, '/api')
  });

  mountProxy('/test/chat/api', GLAMA_PROXY_TARGET, {
    id: 'test-chat',
    pathRewrite: (path) => path.replace(/^\/test\/chat\/api/i, '/api')
  });

  mountProxy('/test/mcp0', MCP0_PROXY_TARGET, {
    id: 'test-mcp0',
    pathRewrite: (path) => path.replace(/^\/test\/mcp0/i, '')
  });

  mountProxy('/test/detects/api', DETECTS_PROXY_TARGET, {
    id: 'test-detects',
    pathRewrite: (path) => path.replace(/^\/test\/detects\/api/i, '')
  });

  if (VAJA_PROXY_TARGET) {
    app.use(
      '/test/vaja/api',
      createProxyMiddleware({
        target: VAJA_PROXY_TARGET,
        changeOrigin: true,
        pathRewrite: (path) => path.replace(/^\/test\/vaja\/api/i, ''),
        onProxyReq: (proxyReq) => {
          proxyReq.setHeader('x-dev-host-proxy', 'test-vaja');
        },
        onError: (err, req, res) => {
          console.error('[dev-host] /test/vaja/api proxy error', err.message);
          if (!res.headersSent) {
            res.status(502).json({ error: 'proxy_error', detail: err.message });
          }
        }
      })
    );

    app.get('/test/vaja/api/health', async (_req, res) => {
      try {
        const response = await fetch(`${VAJA_PROXY_TARGET.replace(/\/+$/, '')}/health`);
        const data = await response.json();
        return res.json(data);
      } catch (err) {
        console.error('[dev-host] /test/vaja/api/health error', err);
        return res.status(502).json({ error: 'proxy_error', detail: err.message });
      }
    });
  }

  mountTestStaticRoutes();
  mountWwwStaticRoutes();
  logRouteStack();
};

wireProxies();

app.post('/api/deploy/:slug', (req, res) => {
  if (!requirePublishToken(req, res)) {
    return;
  }

  const slug = req.params.slug;
  if (!deployConfigs[slug]) {
    return res.status(404).json({ error: 'deploy_config_missing', slug });
  }

  try {
    const record = startDeployment(slug);
    res.status(202).json({
      id: record.id,
      slug: record.slug,
      status: record.status,
      startedAt: record.startedAt
    });
  } catch (error) {
    console.error('[dev-host] deploy start failed', error);
    res.status(500).json({ error: 'deploy_start_failed', detail: error.message });
  }
});

app.get('/api/deploy/:id', (req, res) => {
  if (!requirePublishToken(req, res)) {
    return;
  }

  const id = req.params.id;
  const record = deployments.get(id);
  if (!record) {
    return res.status(404).json({ error: 'deploy_not_found', id });
  }

  res.json({
    id: record.id,
    slug: record.slug,
    status: record.status,
    startedAt: record.startedAt,
    finishedAt: record.finishedAt || null,
    exitCode: record.exitCode ?? null,
    log: record.log
  });
});

siteConfigs.forEach((site) => {
  app.use(`/${site.slug}`, buildSiteRouter(site));
});

app.get('/api/health', async (_req, res) => {
  try {
    const proxies = await probeProxyTargets();
    res.json({
      status: overallStatusFromProxies(proxies),
      proxies,
      sites: getSiteStatuses(),
      timestamp: new Date().toISOString()
    });
  } catch (error) {
    console.error('[dev-host] /api/health probe failed', error);
    res.status(500).json({
      status: 'error',
      error: error.message,
      proxies: [],
      sites: getSiteStatuses(),
      timestamp: new Date().toISOString()
    });
  }
});

app.get('/', (_req, res) => {
  const links = siteConfigs
    .map((site) => {
      const localUrl = `${DEV_HOST_BASE_URL}/${site.slug}/`;
      const publicUrl = site.publicUrl || '—';
      return `
      <li class="site-card">
        <header>
          <p class="site-chip">${site.slug}</p>
          <h2>${site.label}</h2>
        </header>
        <div class="url-panel">
          <div class="url-row">
            <span>Local</span>
            <a href="${localUrl}" target="_blank" rel="noreferrer">${localUrl}</a>
          </div>
          <div class="url-row">
            <span>Public</span>
            ${
              publicUrl === '—'
                ? '<p class="url-missing">Not published</p>'
                : `<a href="${publicUrl}" target="_blank" rel="noreferrer">${publicUrl}</a>`
            }
          </div>
        </div>
        <footer>
          <code>/${site.slug}/*</code>
          ${
            deployConfigs[site.slug]
              ? `<button class="publish-btn" data-slug="${site.slug}">Publish to a1.idc1</button>`
              : ''
          }
        </footer>
      </li>`;
    })
    .join('');

  res.send(`<!doctype html>
  <html lang="en">
    <head>
      <meta charset="utf-8" />
      <meta name="viewport" content="width=device-width, initial-scale=1" />
      <title>dev-host gateway</title>
      <style>
        :root { color-scheme: dark; font-family: 'Inter', system-ui, sans-serif; }
        body { margin: 0; padding: clamp(2rem, 3vw, 3.5rem); background: #050812; color: #f5f7ff; }
        main { max-width: 920px; margin: 0 auto; display: flex; flex-direction: column; gap: 1.5rem; }
        h1 { margin-bottom: 0.4rem; font-size: clamp(2rem, 3vw, 2.6rem); }
        p { margin: 0; color: rgba(245,247,255,0.75); }
        ul { list-style: none; padding: 0; margin: 0; display: grid; gap: 1.25rem; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); }
        .site-card { padding: 1.5rem; border-radius: 22px; border: 1px solid rgba(255,255,255,0.08); background: linear-gradient(135deg, rgba(38,52,114,0.65), rgba(6,10,22,0.9)); display: flex; flex-direction: column; gap: 1.1rem; box-shadow: 0 25px 60px rgba(4,6,18,0.45); }
        .site-card header { display: flex; flex-direction: column; gap: 0.35rem; }
        .site-card h2 { margin: 0; font-size: 1.25rem; }
        .site-chip { margin: 0; text-transform: uppercase; letter-spacing: 0.24em; font-size: 0.72rem; color: #9acbf3; }
        .url-panel { display: flex; flex-direction: column; gap: 0.65rem; background: rgba(3,6,18,0.45); border-radius: 16px; padding: 0.9rem 1rem; border: 1px solid rgba(255,255,255,0.05); }
        .url-row { display: flex; flex-direction: column; gap: 0.2rem; }
        .url-row span { font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.2em; color: rgba(245,247,255,0.55); }
        .url-row a { color: #8cf0d2; font-weight: 600; text-decoration: none; word-break: break-all; }
        .url-row a:hover { text-decoration: underline; }
        .url-missing { margin: 0; color: rgba(245,247,255,0.45); font-style: italic; }
        footer { display: flex; flex-direction: column; gap: 0.6rem; }
        footer code { color: #9ab0d6; font-size: 0.92rem; }
        .publish-btn { appearance: none; border: 1px solid rgba(140,240,210,0.4); background: rgba(9,18,32,0.9); color: #8cf0d2; font-weight: 600; border-radius: 999px; padding: 0.4rem 1rem; cursor: pointer; transition: opacity 0.2s ease, transform 0.2s ease; }
        .publish-btn:hover:not([disabled]) { opacity: 0.9; transform: translateY(-1px); }
        .publish-btn[disabled] { opacity: 0.55; cursor: not-allowed; }
      </style>
    </head>
    <body>
      <main>
        <header class="page-head">
          <div>
            <h1>dev-host gateway</h1>
            <p>Pick a site namespace to preview:</p>
          </div>
          <button id="clear-token" class="publish-btn subtle" type="button" disabled>Clear token</button>
        </header>
        <ul>${links}</ul>
        <section id="deploy-status" aria-live="polite"></section>
      </main>
      <script>
        (function () {
          const tokenKey = 'devHostPublishToken';
          const tokenStore = window.sessionStorage;
          const statusList = document.getElementById('deploy-status');
          const activeJobs = new Map();
          const clearBtn = document.getElementById('clear-token');

          const getToken = () => tokenStore.getItem(tokenKey) || '';
          const setToken = (value) => {
            if (value) {
              tokenStore.setItem(tokenKey, value);
            } else {
              tokenStore.removeItem(tokenKey);
            }
            if (clearBtn) {
              clearBtn.disabled = !getToken();
            }
          };

          if (clearBtn) {
            clearBtn.addEventListener('click', () => {
              setToken('');
              alert('Publish token cleared for this tab.');
            });
            clearBtn.disabled = !getToken();
          }

          const renderStatus = () => {
            if (!statusList) return;
            const rows = Array.from(activeJobs.values())
              .sort((a, b) => (a.startedAt < b.startedAt ? 1 : -1))
              .map((job) => {
                const heading = \`#\${job.id.slice(0, 8)} · \${job.slug} · \${job.status}\`;
                const log = job.log?.slice(-8).join('\\n') || 'Waiting for output...';
                return \`
                  <article class="deploy-card">
                    <header>
                      <h3>\${heading}</h3>
                      <small>\${new Date(job.startedAt).toLocaleTimeString()}</small>
                    </header>
                    <pre>\${log.replace(/</g, '&lt;')}</pre>
                  </article>\`;
              })
              .join('');
            statusList.innerHTML = rows || '';
          };

          const updateJob = (data) => {
            activeJobs.set(data.id, data);
            if (['succeeded', 'failed'].includes(data.status)) {
              setTimeout(() => {
                activeJobs.delete(data.id);
                renderStatus();
              }, 15000);
            }
            renderStatus();
          };

          const pollJob = async (id, token) => {
            try {
              const response = await fetch(\`/api/deploy/\${id}\`, {
                headers: { Authorization: \`Bearer \${token}\` }
              });
              if (response.status === 401) {
                window.localStorage.removeItem(tokenKey);
                return;
              }
              if (!response.ok) return;
              const data = await response.json();
              updateJob(data);
              if (!['succeeded', 'failed'].includes(data.status)) {
                setTimeout(() => pollJob(id, token), 3000);
              }
            } catch (error) {
              console.error('Polling error', error);
            }
          };

          const ensureToken = () => {
            let token = getToken();
            if (!token) {
              token = window.prompt('Enter publish token');
              if (token) {
                setToken(token.trim());
              }
            }
            return token?.trim();
          };

          const handleDeploy = async (slug, button) => {
            const token = ensureToken();
            if (!token) return;

            button.disabled = true;
            const original = button.textContent;
            button.textContent = 'Publishing...';
            try {
              const response = await fetch(\`/api/deploy/\${slug}\`, {
                method: 'POST',
                headers: {
                  Authorization: \`Bearer \${token}\`
                }
              });
              if (response.status === 401) {
                setToken('');
                alert('Unauthorized: token cleared, please enter again.');
                return;
              }
              const raw = await response.text();
              let data = null;
              if (raw) {
                try {
                  data = JSON.parse(raw);
                } catch (parseError) {
                  if (response.ok) {
                    throw new Error('Server returned invalid JSON');
                  }
                }
              }
              if (!response.ok) {
                const detail =
                  (data && (data.error || data.detail)) || raw || \`HTTP \${response.status}\`;
                throw new Error(detail);
              }
              if (!data) {
                throw new Error('Empty response from server');
              }
              updateJob({ id: data.id, slug: data.slug, status: data.status, startedAt: data.startedAt, log: [] });
              pollJob(data.id, token);
            } catch (error) {
              console.error(error);
              alert('Deploy failed: ' + (error?.message || 'unknown error'));
            } finally {
              button.disabled = false;
              button.textContent = original;
            }
          };

          document.querySelectorAll('.publish-btn').forEach((btn) => {
            btn.addEventListener('click', () => handleDeploy(btn.dataset.slug, btn));
          });
        })();
      </script>
    </body>
  </html>`);
});

app.listen(PORT, () => {
  console.log(`[dev-host] listening on port ${PORT}`);
});
