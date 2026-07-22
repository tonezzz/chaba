import { createReadStream, readFileSync, writeFileSync } from 'node:fs';
import { stat } from 'node:fs/promises';
import { extname, join, normalize } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createServer } from 'node:http';
import { timingSafeEqual } from 'node:crypto';
import { WebSocketServer, WebSocket } from 'ws';

const port = Number.parseInt(process.env.PORT ?? '8080', 10);
const basicAuthUser = process.env.BASIC_AUTH_USER;
const basicAuthPassword = process.env.BASIC_AUTH_PASSWORD;
const publicDirectory = fileURLToPath(new URL('./public/', import.meta.url));
const statusFile = process.env.STATUS_FILE ?? normalize(join(publicDirectory, '..', 'status.json'));
const reportToken = process.env.REPORT_TOKEN;
const knownHostNames = ['Tony Dell', 'Tony Omen', 'Android TV Box'];
const reportStaleMs = Number.parseInt(process.env.REPORT_STALE_MS ?? '120000', 10);
function loadStatuses() {
  try { return JSON.parse(readFileSync(statusFile, 'utf8')); } catch { return []; }
}
const contentTypes = {
  '.css': 'text/css; charset=utf-8',
  '.html': 'text/html; charset=utf-8',
  '.ico': 'image/x-icon',
  '.jpg': 'image/jpeg',
  '.js': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.png': 'image/png',
  '.svg': 'image/svg+xml'
};

function matchesSecret(value, secret) {
  const valueBuffer = Buffer.from(value);
  const secretBuffer = Buffer.from(secret);
  return valueBuffer.length === secretBuffer.length && timingSafeEqual(valueBuffer, secretBuffer);
}

function isAuthorized(request) {
  const authorization = request.headers.authorization;
  if (!authorization?.startsWith('Basic ')) return false;

  try {
    const credentials = Buffer.from(authorization.slice(6), 'base64').toString('utf8');
    const separatorIndex = credentials.indexOf(':');
    if (separatorIndex === -1) return false;

    const username = credentials.slice(0, separatorIndex);
    const password = credentials.slice(separatorIndex + 1);
    return matchesSecret(username, basicAuthUser) && matchesSecret(password, basicAuthPassword);
  } catch {
    return false;
  }
}

const server = createServer(async (request, response) => {
  response.setHeader('X-Content-Type-Options', 'nosniff');
  response.setHeader('X-Frame-Options', 'SAMEORIGIN');
  response.setHeader('Referrer-Policy', 'strict-origin-when-cross-origin');
  response.setHeader('Strict-Transport-Security', 'max-age=31536000');

  const pathname = decodeURIComponent(new URL(request.url ?? '/', 'http://localhost').pathname);

  if ((request.headers.upgrade || '').toLowerCase() === 'websocket' && (pathname === '/tunnel' || pathname === '/connect')) {
    server.emit('upgrade', request, request.socket, Buffer.alloc(0));
    return;
  }

  if (pathname === '/health') {
    response.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
    response.end(JSON.stringify({ status: 'ok' }));
    return;
  }

  if (pathname === '/api/report' && request.method === 'POST') {
    const providedToken = new URL(request.url, 'http://localhost').searchParams.get('token') ?? request.headers['x-report-token'];
    if (reportToken && providedToken !== reportToken) {
      response.writeHead(403, { 'Content-Type': 'text/plain; charset=utf-8' });
      response.end('Forbidden');
      return;
    }

    const chunks = [];
    for await (const chunk of request) chunks.push(chunk);
    const body = Buffer.concat(chunks).toString('utf8');
    try {
      const report = JSON.parse(body);
      if (typeof report.name !== 'string' || typeof report.status !== 'string') {
        throw new Error('name and status are required');
      }
      const statuses = loadStatuses();
      const idx = statuses.findIndex((s) => s.name === report.name);
      const record = { name: report.name, status: report.status, reportedAt: Date.now() };
      if (report.temp !== undefined) record.temp = report.temp;
      if (report.fan !== undefined) record.fan = report.fan;
      if (idx === -1) statuses.push(record); else statuses[idx] = record;
      writeFileSync(statusFile, JSON.stringify(statuses, null, 2));
      response.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
      response.end(JSON.stringify({ ok: true }));
    } catch (err) {
      response.writeHead(400, { 'Content-Type': 'application/json; charset=utf-8' });
      response.end(JSON.stringify({ error: err.message }));
    }
    return;
  }

  if (!basicAuthUser || !basicAuthPassword) {
    response.writeHead(503, { 'Content-Type': 'text/plain; charset=utf-8' });
    response.end('Authentication is not configured');
    return;
  }

  if (!isAuthorized(request)) {
    response.writeHead(401, {
      'Content-Type': 'text/plain; charset=utf-8',
      'WWW-Authenticate': 'Basic realm="chaba.h3", charset="UTF-8"'
    });
    response.end('Authentication required');
    return;
  }

  if (pathname === '/api/hosts') {
    const statuses = loadStatuses();
    const now = Date.now();
    const probes = knownHostNames.map((name) => {
      const rec = statuses.find((s) => s.name === name);
      const online = rec && rec.status === 'online' && (now - rec.reportedAt) < reportStaleMs;
      return { name, status: online ? 'online' : 'offline' };
    });

    response.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
    response.end(JSON.stringify(probes));
    return;
  }

  if (pathname.startsWith('/api/status/')) {
    const name = decodeURIComponent(pathname.slice('/api/status/'.length));
    const statuses = loadStatuses();
    const rec = statuses.find((s) => s.name === name);
    if (!rec) {
      response.writeHead(404, { 'Content-Type': 'application/json; charset=utf-8' });
      response.end(JSON.stringify({ error: 'not found' }));
      return;
    }
    response.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
    response.end(JSON.stringify(rec));
    return;
  }

  const requestedPath = pathname === '/' ? 'index.html' : pathname === '/hosts' || pathname === '/hosts/' ? 'hosts/index.html' : pathname === '/tony-omen' || pathname === '/tony-omen/' ? 'tony-omen/index.html' : pathname.slice(1);
  const filePath = normalize(join(publicDirectory, requestedPath));

  if (!filePath.startsWith(publicDirectory)) {
    response.writeHead(403, { 'Content-Type': 'text/plain; charset=utf-8' });
    response.end('Forbidden');
    return;
  }

  try {
    const file = await stat(filePath);
    if (!file.isFile()) throw new Error('Not a file');

    response.writeHead(200, {
      'Content-Type': contentTypes[extname(filePath).toLowerCase()] ?? 'application/octet-stream',
      'Content-Length': file.size
    });
    createReadStream(filePath).pipe(response);
  } catch {
    response.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
    response.end('Not found');
  }
});

// WebSocket tunnel endpoints
const tunnelToken = process.env.TUNNEL_TOKEN;
const wssClient = new WebSocketServer({ noServer: true });
const wssUser = new WebSocketServer({ noServer: true });
let tunnelClient = null;
let tunnelUser = null;

function checkTunnelToken(request) {
  if (!tunnelToken) return true;
  const token = new URL(request.url, 'http://localhost').searchParams.get('token');
  return token === tunnelToken;
}

wssClient.on('connection', (ws) => {
  tunnelClient = ws;
  ws.on('message', (data) => {
    if (tunnelUser && tunnelUser.readyState === WebSocket.OPEN) {
      tunnelUser.send(data);
    }
  });
  ws.on('close', () => {
    tunnelClient = null;
    if (tunnelUser) tunnelUser.close();
  });
  ws.on('error', (err) => console.error('tunnel client error', err.message));
});

wssUser.on('connection', (ws) => {
  if (!tunnelClient || tunnelClient.readyState !== WebSocket.OPEN) {
    ws.close();
    return;
  }
  if (tunnelUser) tunnelUser.close();
  tunnelUser = ws;
  ws.on('message', (data) => {
    if (tunnelClient && tunnelClient.readyState === WebSocket.OPEN) {
      tunnelClient.send(data);
    }
  });
  ws.on('close', () => {
    tunnelUser = null;
  });
  ws.on('error', (err) => console.error('tunnel user error', err.message));
});

server.on('upgrade', (request, socket, head) => {
  if (!checkTunnelToken(request)) {
    socket.destroy();
    return;
  }
  const pathname = new URL(request.url, 'http://localhost').pathname;
  if (pathname === '/tunnel') {
    wssClient.handleUpgrade(request, socket, head, (ws) => {
      wssClient.emit('connection', ws, request);
    });
  } else if (pathname === '/connect') {
    wssUser.handleUpgrade(request, socket, head, (ws) => {
      wssUser.emit('connection', ws, request);
    });
  } else {
    socket.destroy();
  }
});

server.listen(port, '0.0.0.0', () => {
  process.stdout.write(`chaba.h3 listening on port ${port}\n`);
});
