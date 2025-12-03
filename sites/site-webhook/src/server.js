import crypto from 'crypto';
import { spawn } from 'child_process';
import express from 'express';
import morgan from 'morgan';
import path from 'path';
import { fileURLToPath } from 'url';
import dotenv from 'dotenv';

dotenv.config();

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const app = express();
const PORT = process.env.PORT || 3040;
const WEBHOOK_SECRET = (process.env.NODE1_WEBHOOK_SECRET || '').trim();
const DEPLOY_SCRIPT =
  process.env.DEPLOY_SCRIPT || path.resolve(__dirname, '..', '..', '..', 'scripts', 'pull-node-1.sh');

const rawBodyBuffer = (req, _res, buffer, encoding) => {
  if (buffer && buffer.length) {
    req.rawBody = encoding ? buffer.toString(encoding) : buffer.toString();
  }
};

app.use(morgan('combined'));
app.use(express.json({ verify: rawBodyBuffer }));

const verifySignature = (signatureHeader, payload) => {
  if (!WEBHOOK_SECRET) return false;
  if (typeof signatureHeader !== 'string' || !signatureHeader.startsWith('sha256=')) {
    return false;
  }
  const provided = signatureHeader.slice('sha256='.length);
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
      stdio: 'inherit',
      detached: true
    });
    child.on('error', reject);
    child.on('close', (code) => {
      if (code === 0) resolve();
      else reject(new Error(`deploy_script_exit_${code}`));
    });
  });

app.post('/hooks/deploy', async (req, res) => {
  const signature = req.get('X-Hub-Signature-256');
  const event = req.get('X-GitHub-Event');

  if (!req.rawBody || !verifySignature(signature, req.rawBody)) {
    return res.status(401).json({ error: 'invalid_signature' });
  }

  if (event !== 'push') {
    return res.status(202).json({ status: 'ignored', detail: `event ${event}` });
  }

  try {
    runDeployScript().catch((err) => console.error('[site-webhook] deploy failed', err));
    res.status(202).json({ status: 'accepted' });
  } catch (error) {
    console.error('[site-webhook] failed to trigger deploy', error);
    res.status(500).json({ error: 'deploy_failed' });
  }
});

app.get('/health', (_req, res) => {
  res.json({ status: 'ok', webhookConfigured: Boolean(WEBHOOK_SECRET), script: DEPLOY_SCRIPT });
});

app.listen(PORT, () => {
  console.log(`site-webhook listening on ${PORT}`);
});
