import path from 'path';
import express from 'express';
import morgan from 'morgan';
import { fileURLToPath } from 'url';
import dotenv from 'dotenv';

dotenv.config();

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const app = express();
const PORT = process.env.PORT || 3000;

app.use(morgan('dev'));
app.use(express.json());
app.use(express.static(path.join(__dirname, '..', 'public')));

const availableLinks = [
  { path: '/', label: 'Landing page' },
  { path: '/api/health', label: 'Health check (JSON)' },
  { path: '/api/greeting?name=Surf', label: 'Greeting API' },
  { path: '/chat', label: 'Glama chat panel' },
  { path: '/logger', label: 'Logger demo' }
];

app.get('/tony', (_req, res) => {
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
        <ul>
          ${availableLinks
            .map(
              (link) =>
                `<li><a href="${link.path}" target="_blank" rel="noreferrer">${link.label}</a><span class="path">${link.path}</span></li>`
            )
            .join('')}
        </ul>
      </main>
    </body>
  </html>`;
  res.send(html);
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
