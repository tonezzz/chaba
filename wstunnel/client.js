const WebSocket = require('ws');
const net = require('net');

const SERVER = process.env.TUNNEL_SERVER || 'wss://tony-omen.taila0626a.ts.net:3009/tunnel/tony-dell';
const LOCAL_HOST = process.env.LOCAL_HOST || '127.0.0.1';
const LOCAL_PORT = parseInt(process.env.LOCAL_PORT || '22', 10);

function connect() {
  const ws = new WebSocket(SERVER);
  let tcp = null;
  let tcpQueue = [];

  ws.on('open', () => {
    console.log('connected to tunnel server');
    tcp = net.createConnection(LOCAL_PORT, LOCAL_HOST, () => {
      console.log(`connected to ${LOCAL_HOST}:${LOCAL_PORT}`);
      for (const buf of tcpQueue) {
        ws.send(buf);
      }
      tcpQueue = [];
    });

    tcp.on('data', (data) => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(data);
      }
    });

    tcp.on('close', () => {
      ws.close();
    });

    tcp.on('error', (err) => {
      console.error('tcp error', err.message);
      ws.close();
    });
  });

  ws.on('message', (data) => {
    if (tcp && !tcp.destroyed) {
      tcp.write(data);
    }
  });

  ws.on('close', () => {
    console.log('tunnel closed, reconnecting in 5s');
    if (tcp && !tcp.destroyed) tcp.end();
    setTimeout(connect, 5000);
  });

  ws.on('error', (err) => {
    console.error('ws error', err.message);
  });
}

connect();
