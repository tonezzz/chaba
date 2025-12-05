import path from 'path';
import express from 'express';
import morgan from 'morgan';
import multer from 'multer';
import fetch from 'node-fetch';
import { fileURLToPath } from 'url';
import dotenv from 'dotenv';

dotenv.config();

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const app = express();
const PORT = process.env.PORT || 3000;

const upload = multer({
  storage: multer.memoryStorage(),
  limits: {
    fileSize: 10 * 1024 * 1024 // 10 MB
  }
});

const GLAMA_API_URL = (process.env.GLAMA_API_URL || process.env.GLAMA_URL || '').trim();
const GLAMA_API_KEY = (process.env.GLAMA_API_KEY || '').trim();
const GLAMA_MODEL_VISION =
  (process.env.GLAMA_MODEL_VISION || process.env.GLAMA_MODEL || process.env.GLAMA_MODEL_DEFAULT || '').trim() ||
  'gpt-4o-mini';
const GLAMA_TEMPERATURE = Number.isFinite(Number(process.env.GLAMA_TEMPERATURE))
  ? Number(process.env.GLAMA_TEMPERATURE)
  : 0.1;
const GLAMA_MAX_TOKENS = Number.isFinite(Number(process.env.GLAMA_MAX_TOKENS))
  ? Number(process.env.GLAMA_MAX_TOKENS)
  : 800;
const BASE_SYSTEM_PROMPT =
  process.env.VISION_SYSTEM_PROMPT ||
  'You are Surf Thailand’s vision analyst. Reply strictly in JSON with keys description and objects.';

const isGlamaReady = () => Boolean(GLAMA_API_URL && GLAMA_API_KEY);

const ensureGlamaReady = (res) => {
  if (isGlamaReady()) {
    return true;
  }
  res.status(503).json({ error: 'glama_unconfigured' });
  return false;
};

const callVisionModel = async ({ base64Image, mimeType, prompt }) => {
  if (!isGlamaReady()) {
    throw new Error('glama_unconfigured');
  }
  const messages = [
    {
      role: 'system',
      content: BASE_SYSTEM_PROMPT
    },
    {
      role: 'user',
      content: [
        {
          type: 'input_text',
          text: `${prompt}\nRespond as JSON {"description": "...", "objects":[{"label":"","confidence":0-1,"detail":""}]}.`
        },
        {
          type: 'input_image',
          image_url: {
            url: `data:${mimeType};base64,${base64Image}`
          }
        }
      ]
    }
  ];

  const payload = {
    model: GLAMA_MODEL_VISION,
    temperature: GLAMA_TEMPERATURE,
    max_tokens: GLAMA_MAX_TOKENS,
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
  const rawContent = data?.choices?.[0]?.message?.content;
  // content might be array of blocks or a string
  const text =
    typeof rawContent === 'string'
      ? rawContent
      : Array.isArray(rawContent)
      ? rawContent
          .map((entry) => {
            if (typeof entry === 'string') return entry;
            if (entry?.text) return entry.text;
            if (entry?.content) return entry.content;
            return '';
          })
          .join('\n')
          .trim()
      : '';

  return { data, text };
};

app.use(morgan('dev'));
app.use(express.json({ limit: '2mb' }));
app.use(express.static(path.join(__dirname, '..', 'public')));

const availableLinks = [
  { path: '/', label: 'Landing page' },
  { path: '/api/health', label: 'Health check (JSON)' },
  { path: '/api/greeting?name=Surf', label: 'Greeting API' },
  { path: '/chat', label: 'Glama chat panel' },
  { path: '/logger', label: 'Logger demo' },
  { path: '/test/detects', label: 'Vision detects panel' }
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

app.post('/api/detects/analyze', upload.single('photo'), async (req, res) => {
  if (!ensureGlamaReady(res)) {
    return;
  }
  if (!req.file) {
    return res.status(400).json({ error: 'photo_required' });
  }
  const prompt = (req.body?.prompt || '').toString().trim();
  if (!prompt) {
    return res.status(400).json({ error: 'prompt_required' });
  }

  const mimeType = req.file.mimetype || 'image/jpeg';
  const base64Image = req.file.buffer.toString('base64');
  const startedAt = Date.now();

  try {
    const { data, text } = await callVisionModel({ base64Image, mimeType, prompt });
    const elapsed = Date.now() - startedAt;

    let parsed = null;
    if (text) {
      try {
        parsed = JSON.parse(text);
      } catch {
        const cleaned = text
          .trim()
          .replace(/```json/gi, '')
          .replace(/```/g, '')
          .trim();
        try {
          parsed = JSON.parse(cleaned);
        } catch {
          parsed = null;
        }
      }
    }

    const description = parsed?.description || text || 'No description returned.';
    const objects = Array.isArray(parsed?.objects) ? parsed.objects : [];

    res.json({
      description,
      objects,
      raw: data,
      model: data?.model || GLAMA_MODEL_VISION,
      latencyMs: elapsed
    });
  } catch (error) {
    console.error('[site-man] vision analyze failed', error);
    res.status(502).json({ error: error.message || 'glama_vision_failed' });
  }
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
