import fs from 'fs';
import path from 'path';
import express from 'express';
import morgan from 'morgan';
import { createProxyMiddleware } from 'http-proxy-middleware';
import { spawn } from 'child_process';
import { randomUUID } from 'crypto';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const app = express();
const PORT = process.env.PORT || 3000;
const DEV_HOST_BASE_URL = (process.env.DEV_HOST_BASE_URL || 'http://dev-host:3100').replace(/\/+$/, '');
const DEV_HOST_PUBLISH_TOKEN = (process.env.DEV_HOST_PUBLISH_TOKEN || '').trim();
const GLAMA_PROXY_TARGET =
  process.env.GLAMA_PROXY_TARGET || process.env.DEV_HOST_GLAMA_TARGET || 'http://127.0.0.1:4020';
const DETECTS_PROXY_TARGET =
  process.env.DETECTS_PROXY_TARGET || process.env.DEV_HOST_DETECTS_TARGET || 'http://host.docker.internal:4120';

const workspaceRoot = path.resolve(__dirname, '..', '..');

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
    root: path.join(workspaceRoot, 'a1-idc1'),
    publicUrl: 'https://a1.idc1.surf-thailand.com'
  },
  {
    slug: 'idc1',
    label: 'IDC1 preview',
    root: path.join(workspaceRoot, 'idc1'),
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

app.use(
  '/test/chat/api',
  createProxyMiddleware({
    target: GLAMA_PROXY_TARGET,
    changeOrigin: true,
    pathRewrite: (path) => path.replace(/^\/test\/chat\/api/i, '/api'),
    onProxyReq: (proxyReq) => {
      proxyReq.setHeader('x-dev-host-proxy', 'test-chat');
    },
    onError: (err, req, res) => {
      console.error('[dev-host] /test/chat/api proxy error', err.message);
      if (!res.headersSent) {
        res.status(502).json({ error: 'proxy_error', detail: err.message });
      }
    }
  })
);

app.use(
  '/test/detects/api',
  createProxyMiddleware({
    target: DETECTS_PROXY_TARGET,
    changeOrigin: true,
    pathRewrite: (path) => path.replace(/^\/test\/detects\/api/i, ''),
    onProxyReq: (proxyReq) => {
      proxyReq.setHeader('x-dev-host-proxy', 'test-detects');
    },
    onError: (err, req, res) => {
      console.error('[dev-host] /test/detects/api proxy error', err.message);
      if (!res.headersSent) {
        res.status(502).json({ error: 'proxy_error', detail: err.message });
      }
    }
  })
);

const additionalStaticRoutes = [
  {
    basePath: '/test/chat',
    roots: [path.join(workspaceRoot, 'a1-idc1', 'test', 'chat')],
    spa: true
  },
  {
    basePath: '/test/agents',
    roots: [path.join(workspaceRoot, 'a1-idc1', 'test', 'agents')],
    spa: true
  },
  {
    basePath: '/test/detects',
    roots: [path.join(workspaceRoot, 'a1-idc1', 'test', 'detects')],
    spa: true
  },
  {
    basePath: '/test',
    roots: [path.join(workspaceRoot, 'a1-idc1', 'test')],
    spa: true
  }
];

additionalStaticRoutes.forEach(({ basePath, roots, spa }) => {
  const router = express.Router();
  const resolvedRoots = roots.filter((dir) => fs.existsSync(dir));

  if (!resolvedRoots.length) {
    router.use((_req, res) => {
      res.status(404).json({ error: 'static_root_missing', basePath });
    });
  } else {
    resolvedRoots.forEach((dir) => router.use(express.static(dir, { fallthrough: true })));

    if (spa) {
      router.use((_req, res, next) => {
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

app.get('/api/health', (_req, res) => {
  res.json({
    status: 'ok',
    sites: siteConfigs.map((site) => ({ slug: site.slug, rootExists: fs.existsSync(site.root) })),
    timestamp: new Date().toISOString()
  });
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
              ? `<button class="publish-btn" data-slug="${site.slug}">Publish to a1.idc-1</button>`
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
        <h1>dev-host gateway</h1>
        <p>Pick a site namespace to preview:</p>
        <ul>${links}</ul>
      </main>
      <script>
        (function () {
          const tokenKey = 'devHostPublishToken';
          const ensureToken = () => {
            let token = window.localStorage.getItem(tokenKey);
            if (!token) {
              token = window.prompt('Enter publish token');
              if (token) {
                window.localStorage.setItem(tokenKey, token.trim());
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
                window.localStorage.removeItem(tokenKey);
                alert('Unauthorized: token cleared, please enter again.');
                return;
              }
              const data = await response.json();
              if (!response.ok) {
                throw new Error(data?.error || 'Deploy failed');
              }
              alert(\`Deploy started (#\${data.id}). Use the API to monitor status.\`);
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
