import { createReadStream, readFileSync } from 'node:fs';
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
const hostsFile = process.env.CHABA_HOSTS_FILE ?? normalize(join(publicDirectory, '..', 'hosts.json'));
let configuredHosts = [];
try {
  const envHosts = process.env.CHABA_HOSTS;
  configuredHosts = envHosts ? JSON.parse(envHosts) : JSON.parse(readFileSync(hostsFile, 'utf8'));
} catch {}
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

  if (pathname === '/health') {
    response.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
    response.end(JSON.stringify({ status: 'ok' }));
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
    const probes = await Promise.all(configuredHosts.map(async (host) => {
      const start = Date.now();
      try {
        await fetch(host.url, { signal: AbortSignal.timeout(5000) });
        return { name: host.name, status: 'online', response_ms: Date.now() - start };
      } catch {
        return { name: host.name, status: 'offline' };
      }
    }));

    response.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
    response.end(JSON.stringify(probes));
    return;
  }

  const requestedPath = pathname === '/' ? 'index.html' : pathname === '/hosts' || pathname === '/hosts/' ? 'hosts/index.html' : pathname.slice(1);
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
