const net = require('net');
const WebSocket = require('ws');

const LOCAL_PORT = parseInt(process.env.LOCAL_PORT || '2222', 10);
const SERVER = process.env.TUNNEL_SERVER || 'wss://chaba.h3.gizmo-thailand.com/connect/tony-dell';

const server = net.createServer((socket) => {
  console.log('user connected to local proxy');
  const ws = new WebSocket(SERVER);
  let queue = [];

  ws.on('open', () => {
    console.log('connected to tunnel server');
    for (const buf of queue) {
      ws.send(buf);
    }
    queue = [];
  });

  ws.on('message', (data) => {
    if (!socket.destroyed) {
      socket.write(data);
    }
  });

  ws.on('close', () => {
    if (!socket.destroyed) socket.end();
  });

  ws.on('error', (err) => {
    console.error('ws error', err.message);
    if (!socket.destroyed) socket.end();
  });

  socket.on('data', (data) => {
    if (ws.readyState === WebSocket.OPEN) {
      ws.send(data);
    } else {
      queue.push(data);
    }
  });

  socket.on('close', () => {
    ws.close();
  });

  socket.on('error', (err) => {
    console.error('tcp error', err.message);
    ws.close();
  });
});

server.listen(LOCAL_PORT, () => {
  console.log(`local proxy listening on 127.0.0.1:${LOCAL_PORT}`);
});
