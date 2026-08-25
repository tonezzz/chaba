import { createReadStream } from 'node:fs';
import { stat } from 'node:fs/promises';
import { extname, join, normalize } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createServer, request as httpRequest } from 'node:http';
import { request as httpsRequest } from 'node:https';
import { connect as netConnect } from 'node:net';
import { connect as tlsConnect } from 'node:tls';

const port = Number.parseInt(process.env.PORT ?? '8080', 10);
const publicDirectory = fileURLToPath(new URL('./public/', import.meta.url));
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

const GEMINI_LIVE_API = process.env.GEMINI_LIVE_API_URL || 'https://tony-dell.taila0626a.ts.net:8443/api/rview-live';
const RVIEW_API = process.env.RVIEW_API_URL || 'https://tony-dell.taila0626a.ts.net:8443/apps/rview/api';
// rview-live is the chaba.h3 name for the same Gemini Live backend.
const RVIEW_LIVE_API = process.env.RVIEW_LIVE_API_URL || GEMINI_LIVE_API;

function rewriteHost(headers, host) {
  const copy = { ...headers };
  copy.host = host;
  delete copy.Host;
  return copy;
}

function upstreamPath(target, original, prefix) {
  const base = target.pathname.replace(/\/$/, '') || '';
  const suffix = original.pathname.slice(prefix.length) + original.search;
  return base + suffix;
}

function proxyHttp(req, res, base, prefix) {
  const target = new URL(base);
  const original = new URL(req.url ?? '/', 'http://localhost');
  const proxyPath = upstreamPath(target, original, prefix);
  const requestFn = target.protocol === 'https:' ? httpsRequest : httpRequest;
  const defaultPort = target.protocol === 'https:' ? 443 : 80;
  const proxyReq = requestFn({
    hostname: target.hostname,
    port: target.port || defaultPort,
    path: proxyPath,
    method: req.method,
    headers: rewriteHost(req.headers, `${target.hostname}:${target.port || defaultPort}`),
  }, (proxyRes) => {
    res.writeHead(proxyRes.statusCode ?? 502, proxyRes.statusMessage, proxyRes.headers);
    proxyRes.pipe(res);
  });
  proxyReq.on('error', (err) => {
    console.error('proxy error', prefix, err.message);
    res.writeHead(502, { 'Content-Type': 'text/plain; charset=utf-8' });
    res.end('Bad gateway');
  });
  req.pipe(proxyReq);
}

function proxyWs(req, socket, head, base, prefix) {
  const original = new URL(req.url ?? '/', 'http://localhost');
  const target = new URL(base);
  const proxyPath = upstreamPath(target, original, prefix);
  const isSecure = target.protocol === 'https:' || target.protocol === 'wss:';
  const defaultPort = isSecure ? 443 : 80;
  const port = target.port || defaultPort;

  function onConnect(client) {
    let raw = `${req.method} ${proxyPath} HTTP/1.1\r\n`;
    const headers = rewriteHost(req.headers, `${target.hostname}:${port}`);
    for (const [key, value] of Object.entries(headers)) {
      raw += `${key}: ${value}\r\n`;
    }
    raw += '\r\n';
    client.write(raw);
    if (head && head.length) client.write(head);
    socket.pipe(client);
    client.pipe(socket);
  }

  const client = isSecure
    ? tlsConnect({ host: target.hostname, port, servername: target.hostname }, () => onConnect(client))
    : netConnect(port, target.hostname, () => onConnect(client));

  client.on('error', (err) => {
    console.error('ws proxy error', prefix, err.message);
    socket.destroy();
  });
  socket.on('error', () => client.destroy());
}

const server = createServer(async (request, response) => {
  response.setHeader('X-Content-Type-Options', 'nosniff');
  response.setHeader('X-Frame-Options', 'SAMEORIGIN');
  response.setHeader('Referrer-Policy', 'strict-origin-when-cross-origin');
  response.setHeader('Strict-Transport-Security', 'max-age=31536000');

  const url = new URL(request.url ?? '/', 'http://localhost');
  const pathname = decodeURIComponent(url.pathname);

  if (pathname === '/health') {
    response.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
    response.end(JSON.stringify({ status: 'ok' }));
    return;
  }

  if (pathname === '/api/health') {
    // Proxy health check request to chaba health API
    try {
      const healthResponse = await fetch('http://tony-omen.local:3006/api/health');
      if (healthResponse.ok) {
        const healthData = await healthResponse.json();
        response.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
        response.end(JSON.stringify(healthData));
      } else {
        response.writeHead(healthResponse.status, { 'Content-Type': 'application/json; charset=utf-8' });
        response.end(JSON.stringify({ error: 'Health check failed', status: healthResponse.status }));
      }
    } catch (error) {
      response.writeHead(503, { 'Content-Type': 'application/json; charset=utf-8' });
      response.end(JSON.stringify({ error: 'Unable to reach health check service', message: error.message }));
    }
    return;
  }

  if (pathname.startsWith('/api/rview-live/')) {
    proxyHttp(request, response, GEMINI_LIVE_API, '/api/rview-live');
    return;
  }

  if (pathname.startsWith('/api/rview-live/')) {
    proxyHttp(request, response, RVIEW_LIVE_API, '/api/rview-live');
    return;
  }

  if (pathname.startsWith('/apps/rview/api/')) {
    proxyHttp(request, response, RVIEW_API, '/apps/rview/api');
    return;
  }

  const requestedPath = pathname === '/' ? 'index.html' : pathname.slice(1);
  let filePath = normalize(join(publicDirectory, requestedPath));

  if (!filePath.startsWith(publicDirectory)) {
    response.writeHead(403, { 'Content-Type': 'text/plain; charset=utf-8' });
    response.end('Forbidden');
    return;
  }

  let file;
  try {
    file = await stat(filePath);
  } catch { /* try index.html below */ }

  if (file && file.isDirectory() && !pathname.endsWith('/') && pathname !== '/') {
    response.writeHead(301, { 'Location': `${pathname}/` });
    response.end();
    return;
  }

  if (!file || !file.isFile()) {
    const indexPath = normalize(join(filePath, 'index.html'));
    if (indexPath.startsWith(publicDirectory)) {
      try {
        file = await stat(indexPath);
        filePath = indexPath;
      } catch { /* will fall through to 404 */ }
    }
  }

  if (!file || !file.isFile()) {
    response.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
    response.end('Not found');
    return;
  }

  response.writeHead(200, {
    'Content-Type': contentTypes[extname(filePath).toLowerCase()] ?? 'application/octet-stream',
    'Content-Length': file.size
  });
  createReadStream(filePath).pipe(response);
});

server.on('upgrade', (request, socket, head) => {
  const url = new URL(request.url ?? '/', 'http://localhost');
  const pathname = decodeURIComponent(url.pathname);
  if (pathname.startsWith('/api/rview-live/')) {
    proxyWs(request, socket, head, GEMINI_LIVE_API, '/api/rview-live');
  } else if (pathname.startsWith('/api/rview-live/')) {
    proxyWs(request, socket, head, RVIEW_LIVE_API, '/api/rview-live');
  } else if (pathname.startsWith('/apps/rview/api/')) {
    proxyWs(request, socket, head, RVIEW_API, '/apps/rview/api');
  } else {
    socket.destroy();
  }
});

server.listen(port, '0.0.0.0', () => {
  process.stdout.write(`Chaba test site listening on port ${port}\n`);
});
