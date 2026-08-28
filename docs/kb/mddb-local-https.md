---
category: operations
---

# Local HTTPS Endpoint for MDDB

This is a reusable recipe for exposing the local MDDB MCP endpoint over HTTPS using `mkcert` and Caddy. It is **not** used by Claude Desktop's connector (which cannot handle MDDB's MCP 2025 protocol), but it is useful for any client that needs a trusted `https://` URL to a local MCP server.

## What it creates

- A local CA trusted by the OS and Chrome/Firefox (`mkcert -install`)
- A certificate for `tony-omen.local`, `localhost`, `127.0.0.1`, and `::1`
- A Caddy reverse proxy on `https://tony-omen.local:9443/mcp` forwarding to `http://localhost:9001`
- A systemd service `caddy-mddb` that starts on boot

## Requirements

- `mkcert`
- `caddy`
- Passwordless `sudo` or root access to install the CA
- Port `9443` free on the host

## Files and commands

### 1. Install tools

```bash
sudo apt install -y mkcert caddy
```

### 2. Create and trust the local CA

```bash
mkdir -p ~/.config/Claude/mddb-certs
mkcert -install
mkcert -cert-file ~/.config/Claude/mddb-certs/cert.pem \
        -key-file ~/.config/Claude/mddb-certs/key.pem \
        tony-omen.local localhost 127.0.0.1 ::1
```

### 3. Caddyfile

Create `~/.config/Claude/mddb-certs/Caddyfile`:

```caddy
{
    auto_https disable_redirects
}

tony-omen.local:9443 {
    tls ~/.config/Claude/mddb-certs/cert.pem ~/.config/Claude/mddb-certs/key.pem
    reverse_proxy localhost:9001
}
```

`auto_https disable_redirects` prevents Caddy from trying to bind port `80` for HTTP-to-HTTPS redirects.

### 4. Systemd service

Create `/etc/systemd/system/caddy-mddb.service`:

```ini
[Unit]
Description=Caddy reverse proxy for mddb HTTPS
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/caddy run --config /home/tony/.config/Claude/mddb-certs/Caddyfile --adapter caddyfile
Restart=on-failure
User=tony
Group=tony
LimitNOFILE=8192

[Install]
WantedBy=multi-user.target
```

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now caddy-mddb
```

### 5. Verify

```bash
curl -s https://tony-omen.local:9443/mcp
# {"error":"MCP-Session-Id required"}
```

## Managing the service

```bash
# Check status
systemctl status caddy-mddb

# Restart after Caddyfile changes
sudo systemctl restart caddy-mddb

# Stop/disable
sudo systemctl stop caddy-mddb
sudo systemctl disable caddy-mddb
```

## Notes

- The certificate files live in `~/.config/Claude/mddb-certs/`.
- The mkcert root CA is at `~/.local/share/mkcert/rootCA.pem`.
- If a client does not use the system trust store (e.g., a Node process with `certifi`), point `NODE_EXTRA_CA_CERTS` or `SSL_CERT_FILE` at `~/.local/share/mkcert/rootCA.pem`.
