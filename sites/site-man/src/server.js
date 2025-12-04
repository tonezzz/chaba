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
const DEPLOY_SCRIPT =
  process.env.DEPLOY_SCRIPT || path.resolve(__dirname, '..', '..', '..', 'scripts', 'pull-node-1.sh');
const TONY_SITES_ROOT = path.resolve(__dirname, '..', '..', 'tony', 'sites');

const rawBodyBuffer = (req, _res, buffer) => {
  if (buffer && buffer.length) {
    req.rawBody = buffer.toString('utf8');
  }
};

app.use(morgan('dev'));
app.use(express.json({ verify: rawBodyBuffer }));
app.use(express.static(path.join(__dirname, '..', 'public')));
app.use(
  '/tony/sites',
  express.static(TONY_SITES_ROOT, {
    extensions: ['html', 'htm']
  })
);

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
    </body>
  </html>`;
    res.send(html);
  } catch (error) {
    console.error('[site-man] Failed to render Tony panel', error);
    res.status(500).send('Tony panel unavailable');
  }
});

app.get('/api/health', (req, res) => {
  res.json({ status: 'ok', node: process.version, timestamp: new Date().toISOString() });
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
