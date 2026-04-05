#!/bin/sh
set -e

echo "Setting up proxy configuration..."

# Create proxy configuration
cat > /app/proxy.js <<'EOF'
const http = require('http');
const url = require('url');

const targetHost = process.env.ONE_MCP_HOST || '0.0.0.0';
const targetPort = process.env.ONE_MCP_PORT || 3050;

const server = http.createServer((req, res) => {
  const targetUrl = `http://${targetHost}:${targetPort}${req.url}`;
  
  const options = {
    hostname: targetHost,
    port: targetPort,
    path: req.url,
    method: req.method,
    headers: req.headers
  };

  const proxyReq = http.request(options, (proxyRes) => {
    res.writeHead(proxyRes.statusCode, proxyRes.headers);
    proxyRes.pipe(res);
  });

  proxyReq.on('error', (err) => {
    console.error('Proxy error:', err);
    res.writeHead(502);
    res.end('Bad Gateway');
  });

  req.pipe(proxyReq);
});

const port = process.env.PROXY_PORT || 3050;
server.listen(port, () => {
  console.log(`Proxy server running on port ${port}`);
});
EOF

echo "Proxy setup completed"
