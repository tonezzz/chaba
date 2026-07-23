import { createReadStream, existsSync, readFileSync, writeFileSync } from 'node:fs';
import { stat } from 'node:fs/promises';
import { extname, join, normalize } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createServer, request as httpRequest } from 'node:http';
import { timingSafeEqual } from 'node:crypto';
import { WebSocketServer, WebSocket } from 'ws';
import { Client as SshClient } from 'ssh2';
import { execSync } from 'node:child_process';

const port = Number.parseInt(process.env.PORT ?? '8080', 10);
const basicAuthUser = process.env.BASIC_AUTH_USER;
const basicAuthPassword = process.env.BASIC_AUTH_PASSWORD;
const publicDirectory = fileURLToPath(new URL('./public/', import.meta.url));
const statusFile = process.env.STATUS_FILE ?? normalize(join(publicDirectory, '..', 'status.json'));
const reportToken = process.env.REPORT_TOKEN;
const knownHostNames = ['Tony Dell', 'Tony Omen', 'Android TV Box'];
const reportStaleMs = Number.parseInt(process.env.REPORT_STALE_MS ?? '120000', 10);
const appRoot = fileURLToPath(new URL('.', import.meta.url));
let versionCommit = process.env.COMMIT_SHA?.trim() ?? '';
if (!versionCommit) {
  try { versionCommit = execSync('git rev-parse --short HEAD', { cwd: appRoot, encoding: 'utf8' }).trim(); } catch { versionCommit = 'unknown'; }
}
const versionBuiltAt = new Date().toISOString();
const sshHost = process.env.SSH_TONYDELL_HOST || '127.0.0.1';
const sshPort = Number.parseInt(process.env.SSH_TONYDELL_PORT || '7022', 10);
const sshUser = process.env.SSH_TONYDELL_USER || '';

function loadSshPrivateKey() {
  const env = process.env.SSH_TONYDELL_PRIVATE_KEY;
  if (env) {
    const v = env.trim();
    if (v.includes('BEGIN OPENSSH PRIVATE KEY') || v.includes('BEGIN RSA PRIVATE KEY')) {
      return Buffer.from(v);
    }
    if (existsSync(v)) return readFileSync(v);
  }
  const path = process.env.SSH_TONYDELL_PRIVATE_KEY_PATH;
  if (path && existsSync(path)) return readFileSync(path);
  return undefined;
}

function loadStatuses() {
  try { return JSON.parse(readFileSync(statusFile, 'utf8')); } catch { return []; }
}

const camerasFile = normalize(join(publicDirectory, 'cameras.json'));
let cameraCache = [];
let cameraCacheRefreshedAt = null;

function pickPlayUrl(cam) {
  const candidates = [cam.hls_url, ...(cam.alt_urls || [])].filter(Boolean);
  return candidates.find(u => u.startsWith('https://')) || cam.hls_url || null;
}

function loadCamerasData() {
  try {
    const data = JSON.parse(readFileSync(camerasFile, 'utf8'));
    cameraCache = (data.cameras || []).filter(c => c.enabled !== false).map(cam => ({
      name: cam.name,
      title: cam.title,
      group: cam.group,
      lat: cam.lat,
      lon: cam.lon,
      source: cam.source,
      stream_type: cam.stream_type,
      stream_status: cam.stream_status,
      description: cam.description,
      perspective: cam.perspective,
      location: cam.location,
      view: cam.view,
      playUrl: pickPlayUrl(cam),
      reachable: false,
      checkedAt: null
    }));
  } catch {
    cameraCache = [];
  }
}

async function refreshCameras() {
  loadCamerasData();
  if (!cameraCache.length) return;
  await Promise.all(cameraCache.map(async cam => {
    if (!cam.playUrl || !cam.playUrl.startsWith('https://')) {
      cam.reachable = false;
      cam.checkedAt = new Date().toISOString();
      return;
    }
    try {
      const res = await fetch(cam.playUrl, { method: 'HEAD', signal: AbortSignal.timeout(8000) });
      cam.reachable = res.ok;
    } catch {
      cam.reachable = false;
    }
    cam.checkedAt = new Date().toISOString();
  }));
  cameraCacheRefreshedAt = new Date().toISOString();
}

loadCamerasData();
refreshCameras();
setInterval(refreshCameras, 60000);
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

  if (pathname === '/api/version') {
    response.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
    response.end(JSON.stringify({ commit: versionCommit, builtAt: versionBuiltAt }));
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

  if (pathname.startsWith('/tony-omen/apps/imagen/api/')) {
    const apiPath = pathname.slice('/tony-omen/apps/imagen/api/'.length);
    const search = new URL(request.url, 'http://localhost').search;
    const proxyReq = httpRequest(`http://127.0.0.1:8000/${apiPath}${search}`, {
      method: request.method,
      headers: { ...request.headers, host: '127.0.0.1:8000' }
    }, (proxyRes) => {
      response.writeHead(proxyRes.statusCode, proxyRes.headers);
      proxyRes.pipe(response);
    });
    proxyReq.on('error', (err) => {
      console.error('imagen proxy error', err.message);
      if (!response.headersSent) {
        response.writeHead(502, { 'Content-Type': 'text/plain; charset=utf-8' });
        response.end('Bad gateway: ' + err.message);
      }
    });
    request.pipe(proxyReq);
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

  if (pathname === '/api/cameras') {
    response.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
    response.end(JSON.stringify({ cameras: cameraCache, refreshedAt: cameraCacheRefreshedAt }));
    return;
  }

  const nameMatch = pathname.match(/^\/api\/cameras\/([^/]+)\/?$/);
  if (nameMatch) {
    const name = decodeURIComponent(nameMatch[1]);
    const cam = cameraCache.find(c => c.name === name);
    if (!cam) {
      response.writeHead(404, { 'Content-Type': 'application/json; charset=utf-8' });
      response.end(JSON.stringify({ error: 'not found' }));
      return;
    }
    response.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
    response.end(JSON.stringify(cam));
    return;
  }

  if (pathname.startsWith('/api/camera-control/')) {
    const apiPath = pathname.slice('/api/camera-control/'.length);
    const search = new URL(request.url, 'http://localhost').search;
    const proxyReq = httpRequest(`http://192.168.1.48:8090/${apiPath}${search}`, {
      method: request.method,
      headers: { ...request.headers, host: '192.168.1.48:8090' }
    }, (proxyRes) => {
      response.writeHead(proxyRes.statusCode, proxyRes.headers);
      proxyRes.pipe(response);
    });
    proxyReq.on('error', (err) => {
      console.error('camera control proxy error', err.message);
      if (!response.headersSent) {
        response.writeHead(502, { 'Content-Type': 'text/plain; charset=utf-8' });
        response.end('Bad gateway: ' + err.message);
      }
    });
    request.pipe(proxyReq);
    return;
  }

  const adjustedPathname = pathname.startsWith('/tony-omen/') ? pathname.slice('/tony-omen'.length) : pathname;
  const requestedPath = adjustedPathname === '/' ? 'index.html' : adjustedPathname.slice(1);
  let filePath = normalize(join(publicDirectory, requestedPath));

  if (!filePath.startsWith(publicDirectory)) {
    response.writeHead(403, { 'Content-Type': 'text/plain; charset=utf-8' });
    response.end('Forbidden');
    return;
  }

  try {
    let file = await stat(filePath);
    if (file.isDirectory()) {
      filePath = normalize(join(filePath, 'index.html'));
      file = await stat(filePath);
    }
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

const wssSsh = new WebSocketServer({ noServer: true });
wssSsh.on('connection', (ws) => {
  if (!sshUser) {
    ws.close(1011, 'SSH user not configured');
    return;
  }
  const key = loadSshPrivateKey();
  if (!key && !process.env.SSH_TONYDELL_PASSWORD) {
    ws.close(1011, 'SSH credentials not configured');
    return;
  }
  const conn = new SshClient();
  let stream = null;
  ws.on('message', (buf) => {
    if (!stream) return;
    try {
      const text = buf.toString('utf8');
      const msg = JSON.parse(text);
      if (msg && msg.type === 'resize') {
        stream.setWindow(msg.rows, msg.cols, 0, 0);
        return;
      }
    } catch {
      // not a resize command; forward raw bytes
    }
    stream.write(buf);
  });
  ws.on('close', () => {
    if (stream) stream.close();
    conn.end();
  });
  conn.on('ready', () => {
    conn.shell({ term: 'xterm-256color', cols: 80, rows: 24 }, (err, s) => {
      if (err) {
        ws.close(1011, err.message);
        conn.end();
        return;
      }
      stream = s;
      stream.on('data', (data) => {
        if (ws.readyState === WebSocket.OPEN) ws.send(data);
      });
      stream.on('close', () => {
        conn.end();
        ws.close();
      });
      stream.on('error', (err) => console.error('ssh stream error', err.message));
    });
  });
  conn.on('error', (err) => {
    console.error('ssh2 error', err.message);
    ws.close();
  });
  conn.on('end', () => {
    if (ws.readyState === WebSocket.OPEN) ws.close();
  });
  conn.connect({
    host: sshHost,
    port: sshPort,
    username: sshUser,
    privateKey: key,
    password: process.env.SSH_TONYDELL_PASSWORD || undefined,
    readyTimeout: 20000,
    keepaliveInterval: 10000
  });
});

server.on('upgrade', (request, socket, head) => {
  const pathname = new URL(request.url, 'http://localhost').pathname;
  if (pathname === '/ws/ssh') {
    if (!isAuthorized(request)) {
      socket.write('HTTP/1.1 401 Unauthorized\r\nWWW-Authenticate: Basic realm="chaba.h3"\r\n\r\n');
      socket.destroy();
      return;
    }
    wssSsh.handleUpgrade(request, socket, head, (ws) => {
      wssSsh.emit('connection', ws, request);
    });
    return;
  }
  if (!checkTunnelToken(request)) {
    socket.destroy();
    return;
  }
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
