const http = require('http');
const WebSocket = require('ws');
const url = require('url');

const PORT = process.env.PORT || 3000;
const TOKEN = process.env.TUNNEL_TOKEN || null;

function hasToken(request) {
  if (!TOKEN) return true;
  const q = url.parse(request.url, true).query;
  return q.token === TOKEN;
}

const server = http.createServer((req, res) => {
  res.writeHead(200);
  res.end('tony-dell / kk-macbook ws tunnel\n');
});

const wssClient = new WebSocket.Server({ noServer: true });
const wssUser = new WebSocket.Server({ noServer: true });

const clients = new Map();
const users = new Map();

function getTarget(pathname) {
  const match = pathname.match(/^\/(?:tunnel|connect)\/(.+)$/);
  return match ? match[1] : null;
}

wssClient.on('connection', (ws, req) => {
  const target = getTarget(url.parse(req.url).pathname) || 'tony-dell';
  console.log(`client connected for target: ${target}`);
  clients.set(target, ws);

  ws.on('message', (data) => {
    const user = users.get(target);
    if (user && user.readyState === WebSocket.OPEN) {
      user.send(data);
    }
  });

  ws.on('close', () => {
    console.log(`client disconnected for target: ${target}`);
    if (clients.get(target) === ws) clients.delete(target);
    const user = users.get(target);
    if (user) user.close();
  });

  ws.on('error', (err) => console.error(`client ws error for ${target}:`, err.message));
});

wssUser.on('connection', (ws, req) => {
  const target = getTarget(url.parse(req.url).pathname) || 'tony-dell';
  const client = clients.get(target);

  if (!client || client.readyState !== WebSocket.OPEN) {
    console.log(`user connected for ${target} but client is offline`);
    ws.close();
    return;
  }

  const existingUser = users.get(target);
  if (existingUser && existingUser !== ws) {
    console.log(`new user connection for ${target}, closing previous`);
    existingUser.close();
  }

  console.log(`user connected for target: ${target}`);
  users.set(target, ws);

  ws.on('message', (data) => {
    const clientWs = clients.get(target);
    if (clientWs && clientWs.readyState === WebSocket.OPEN) {
      clientWs.send(data);
    }
  });

  ws.on('close', () => {
    console.log(`user disconnected for target: ${target}`);
    if (users.get(target) === ws) users.delete(target);
  });

  ws.on('error', (err) => console.error(`user ws error for ${target}:`, err.message));
});

server.on('upgrade', (request, socket, head) => {
  if (!hasToken(request)) {
    socket.destroy();
    return;
  }
  const pathname = url.parse(request.url).pathname;

  if (pathname.startsWith('/tunnel/') || pathname === '/tunnel') {
    wssClient.handleUpgrade(request, socket, head, (ws) => {
      wssClient.emit('connection', ws, request);
    });
  } else if (pathname.startsWith('/connect/') || pathname === '/connect') {
    wssUser.handleUpgrade(request, socket, head, (ws) => {
      wssUser.emit('connection', ws, request);
    });
  } else {
    socket.destroy();
  }
});

server.listen(PORT, () => {
  console.log(`tunnel server listening on port ${PORT}`);
});
