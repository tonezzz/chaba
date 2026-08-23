# tony-dell / kk-macbook WebSocket tunnel

Forwards SSH (or any TCP port) to `tony-dell` or `kk-macbook` through the managed Node.js host `chaba.h3.gizmo-thailand.com`.

## Architecture

- `server.js` runs on `chaba.h3` and bridges two WebSockets per target:
  - `/tunnel/:target` — the connection from the target machine.
  - `/connect/:target` — the connection from the user's laptop.
- `client.js` / `tony-dell-client.py` runs on `tony-dell` and pipes local port `22` to `/tunnel/tony-dell`.
- `kk-macbook-client.py` runs on `kk-macbook` and pipes local port `22` to `/tunnel/kk-macbook`.
- `user-proxy.js` runs on the user's laptop and exposes `127.0.0.1:2222`, forwarding to `/connect/tony-dell`.

## 1. Deploy server on chaba.h3

Upload `server.js`, `package.json`.

```bash
npm install
PORT=3000 TUNNEL_TOKEN=your-secret-token node server.js
```

Expose the process behind `chaba.h3.gizmo-thailand.com` on whatever port/path your managed host uses and map it to `server.js`.

## 2. Deploy tony-dell client

Upload `client.js` or `tony-dell-client.py`.

```bash
TUNNEL_TOKEN=your-secret-token node client.js
# or
TUNNEL_TOKEN=your-secret-token python3 tony-dell-client.py
```

Set `TUNNEL_SERVER` to override the default path, e.g.:

```bash
TUNNEL_SERVER='wss://chaba.h3.gizmo-thailand.com/tunnel/tony-dell?token=your-secret-token' node client.js
```

Use `pm2`, `systemd`, `forever`, or `screen` to keep it running.

## 3. Deploy kk-macbook client

Upload `kk-macbook-client.py` and install websockets:

```bash
pip3 install --user websockets
TUNNEL_TOKEN=your-secret-token python3 kk-macbook-client.py
```

Set `TUNNEL_SERVER` to override the default path:

```bash
TUNNEL_SERVER='wss://chaba.h3.gizmo-thailand.com/tunnel/kk-macbook?token=your-secret-token' python3 kk-macbook-client.py
```

## 4. Run proxy on your laptop

Upload `user-proxy.js`, `package.json`.

```bash
npm install
TUNNEL_SERVER='wss://chaba.h3.gizmo-thailand.com/connect/tony-dell?token=your-secret-token' node user-proxy.js
```

For kk-macbook:

```bash
TUNNEL_SERVER='wss://chaba.h3.gizmo-thailand.com/connect/kk-macbook?token=your-secret-token' node user-proxy.js
```

## 5. SSH

```bash
ssh -p 2222 localhost
```

Or in `~/.ssh/config`:

```text
Host tony-dell-ws
    HostName 127.0.0.1
    Port 2222
    User <your-username>

Host kk-macbook-ws
    HostName 127.0.0.1
    Port 2222
    User <your-username>
```

## Security notes

- Set a strong `TUNNEL_TOKEN` so random clients cannot connect to `/tunnel/:target` and random users cannot use `/connect/:target`.
- This version supports one user connection per target at a time.
