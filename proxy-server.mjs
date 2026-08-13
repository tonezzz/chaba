import { createReadStream } from 'node:fs';
import { stat } from 'node:fs/promises';
import { extname, join, normalize } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createServer } from 'node:http';

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

server.listen(port, '0.0.0.0', () => {
  process.stdout.write(`Chaba test site listening on port ${port}\n`);
});
