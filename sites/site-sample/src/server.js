import crypto from 'crypto';
import { spawn } from 'child_process';
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
const WEBHOOK_SECRET = (process.env.NODE1_WEBHOOK_SECRET || '').trim();
const DEPLOY_SCRIPT =
  process.env.DEPLOY_SCRIPT || path.resolve(__dirname, '..', '..', '..', 'scripts', 'pull-node-1.sh');

const rawBodyBuffer = (req, _res, buffer) => {
  if (buffer && buffer.length) {
    req.rawBody = buffer.toString('utf8');
  }
};

app.use(morgan('dev'));
app.use(express.json({ verify: rawBodyBuffer }));
app.use(express.static(path.join(__dirname, '..', 'public')));

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
