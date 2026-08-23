# tony-dell / kk-macbook WebSocket tunnel

Forwards SSH (or any TCP port) to `tony-dell` or `kk-macbook` through the
`tony-omen` Tailscale node.

## Architecture

- `server.js` runs on `tony-omen` (`tony-omen.taila0626a.ts.net:3009`) and
  bridges two WebSocket paths per target:
  - `/tunnel/:target` — the connection from the target machine.
  - `/connect/:target` — the connection from the user laptop.
- `client.js` / `tony-dell-client.py` runs on `tony-dell` and pipes local port
  `22` to `/tunnel/tony-dell`.
- `kk-macbook-client.py` runs on `kk-macbook` and pipes local port `22` to
  `/tunnel/kk-macbook`.
- `user-proxy.js` runs on the user laptop and exposes `127.0.0.1:2222`,
  forwarding to `/connect/tony-dell`.

The server uses `wss` on port `3009` and is exposed inside the Tailnet via
`tailscale serve --bg --tcp 3009 127.0.0.1:3009`.

If you later want the public `chaba.h3.gizmo-thailand.com` hostname, configure a
Plesk/nginx reverse proxy on `chaba.h3` pointing to
`wss://tony-omen.taila0626a.ts.net:3009`.

## 1. Start the server on tony-omen

```bash
npm install
PORT=3009 \
TLS_CERT=./certs/cert.crt \
TLS_KEY=./certs/key.pem \
TUNNEL_TOKEN=your-secret-token \
node server.js
```

Then in another shell:

```bash
tailscale serve --bg --tcp 3009 127.0.0.1:3009
```

To keep it persistent, run it under `pm2`, `systemd`, `forever`, or `screen`.

## 2. Deploy tony-dell client

```bash
TUNNEL_TOKEN=your-secret-token node client.js
# or
TUNNEL_TOKEN=your-secret-token python3 tony-dell-client.py
```

Set `TUNNEL_SERVER` to override the default path, e.g.:

```bash
TUNNEL_SERVER='wss://tony-omen.taila0626a.ts.net:3009/tunnel/tony-dell?token=your-secret-token' node client.js
```

## 3. Deploy kk-macbook client

```bash
pip3 install --user websockets
TUNNEL_TOKEN=your-secret-token python3 kk-macbook-client.py
```

Set `TUNNEL_SERVER` to override the default path:

```bash
TUNNEL_SERVER='wss://tony-omen.taila0626a.ts.net:3009/tunnel/kk-macbook?token=your-secret-token' python3 kk-macbook-client.py
```

## 4. Run proxy on your laptop

```bash
TUNNEL_SERVER='wss://tony-omen.taila0626a.ts.net:3009/connect/tony-dell?token=your-secret-token' node user-proxy.js
```

For kk-macbook:

```bash
TUNNEL_SERVER='wss://tony-omen.taila0626a.ts.net:3009/connect/kk-macbook?token=your-secret-token' node user-proxy.js
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

- Set a strong `TUNNEL_TOKEN` so random clients cannot connect to
  `/tunnel/:target` and random users cannot use `/connect/:target`.
- This version supports one user connection per target at a time.
- The `wss` certificate is provided by Tailscale; only expose this inside the
  Tailnet unless you also put it behind the Plesk reverse proxy on `chaba.h3`.
