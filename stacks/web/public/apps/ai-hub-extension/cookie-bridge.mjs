import { createServer } from 'http';
import { writeFileSync, mkdirSync } from 'fs';
import { dirname } from 'path';
import { execSync } from 'child_process';
import { homedir } from 'os';

const PORT = process.env.PORT || 9876;
const STORAGE = process.env.STORAGE || `${homedir()}/.notebooklm/profiles/default/storage_state.json`;
const RSYNC_TARGET = process.env.RSYNC_TARGET || '';
const RESTART_CMD = process.env.RESTART_CMD || '';

createServer((req, res) => {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') {
    res.writeHead(204);
    res.end();
    return;
  }

  if (req.method !== 'POST' || req.url !== '/cookies') {
    res.writeHead(404);
    res.end('not found');
    return;
  }

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
      res.writeHead(400);
      res.end(err.message);
    }
  });
}).listen(PORT, () => {
  console.log(`Cookie bridge listening on http://127.0.0.1:${PORT}`);
  console.log(`Storage: ${STORAGE}`);
  if (RSYNC_TARGET) console.log(`Rsync target: ${RSYNC_TARGET}`);
  if (RESTART_CMD) console.log(`Restart: ${RESTART_CMD}`);
});
