import { createServer } from 'http';
import { writeFileSync, mkdirSync } from 'fs';
import { dirname } from 'path';
import { execSync } from 'child_process';
import { homedir } from 'os';

const PORT = process.env.PORT || 9876;
const STORAGE = process.env.STORAGE || `${homedir()}/.notebooklm/profiles/default/storage_state.json`;
const RSYNC_TARGET = process.env.RSYNC_TARGET || '';
const RESTART_CMD = process.env.RESTART_CMD || '';
const DEBUG_DIR = `${homedir()}/.local/ai-hub/debug`;
const DUMP_DIR = `${homedir()}/.local/ai-hub/page-dumps`;

function handleCookies(req, res) {
  let body = '';
  req.on('data', chunk => { body += chunk; });
  req.on('end', () => {
    try {
      const data = JSON.parse(body);
      if (!Array.isArray(data.cookies)) throw new Error('Expected cookies array');

      mkdirSync(dirname(STORAGE), { recursive: true });
      writeFileSync(STORAGE, JSON.stringify(data, null, 2));

      if (RSYNC_TARGET) {
        execSync(`rsync -avz "${STORAGE}" "${RSYNC_TARGET}"`, { stdio: 'inherit' });
      }
      if (RESTART_CMD) {
        execSync(RESTART_CMD, { stdio: 'inherit' });
      }

      res.writeHead(200);
      res.end('ok');
    } catch (err) {
      console.error('cookie-bridge save error:', err.message);
      res.writeHead(400);
      res.end(err.message);
    }
  });
}

function handleDebugScreenshot(req, res) {
  let body = '';
  req.on('data', chunk => { body += chunk; });
  req.on('end', () => {
    try {
      const data = JSON.parse(body);
      if (!data.imageData || typeof data.imageData !== 'string') throw new Error('Expected imageData string');

      const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
      mkdirSync(DEBUG_DIR, { recursive: true });
      const pngPath = `${DEBUG_DIR}/${timestamp}.png`;
      const jsonPath = `${DEBUG_DIR}/${timestamp}.json`;
      const base64 = data.imageData.replace(/^data:image\/png;base64,/, '');
      writeFileSync(pngPath, Buffer.from(base64, 'base64'));
      writeFileSync(jsonPath, JSON.stringify(data.debug || {}, null, 2));

      res.writeHead(200);
      res.end(`png: ${pngPath}\njson: ${jsonPath}`);
    } catch (err) {
      res.writeHead(400);
      res.end(err.message);
    }
  });
}

createServer((req, res) => {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') {
    res.writeHead(204);
    res.end();
    return;
  }

  if (req.method === 'GET' && req.url === '/health') {
    res.writeHead(200);
    res.end('ok');
    return;
  }

  if (req.method === 'POST' && req.url === '/cookies') {
    handleCookies(req, res);
    return;
  }

  if (req.method === 'POST' && req.url === '/debug-screenshot') {
    handleDebugScreenshot(req, res);
    return;
  }

  if (req.method === 'POST' && req.url === '/page-dump') {
    let body = '';
    req.on('data', chunk => { body += chunk; });
    req.on('end', () => {
      try {
        const data = JSON.parse(body);
        if (typeof data.text !== 'string' && typeof data.html !== 'string') {
          throw new Error('Expected text or html');
        }
        const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
        const slug = String(data.title || data.url || 'page').replace(/[^a-z0-9]+/gi, '_').slice(0, 40);
        mkdirSync(DUMP_DIR, { recursive: true });
        const path = `${DUMP_DIR}/${timestamp}_${slug}.json`;
        writeFileSync(path, JSON.stringify({ receivedAt: new Date().toISOString(), ...data }, null, 2));
        res.writeHead(200);
        res.end(`dump: ${path}`);
      } catch (err) {
        res.writeHead(400);
        res.end(err.message);
      }
    });
    return;
  }

  res.writeHead(404);
  res.end('not found');
}).listen(PORT, () => {
  console.log(`Cookie bridge listening on http://127.0.0.1:${PORT}`);
  console.log(`Storage: ${STORAGE}`);
  if (RSYNC_TARGET) console.log(`Rsync target: ${RSYNC_TARGET}`);
  if (RESTART_CMD) console.log(`Restart: ${RESTART_CMD}`);
  console.log(`Debug dir: ${DEBUG_DIR}`);
});
