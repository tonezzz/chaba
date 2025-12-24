# Chaba infrastructure notes

## SSL quick reference

## Ingress (default)

- **HTTP/HTTPS ingress (default)**: Host Caddy is the first receiver for inbound web traffic and should own `80/tcp` + `443/tcp` on hosts that act as public HTTP/HTTPS entrypoints.
- **Routing**: Caddy terminates TLS (when applicable) and routes by hostname/path via `reverse_proxy` to internal services (Docker or host processes).
- **Exceptions**:
  - VPN-only / dev environments may terminate HTTPS in a container (e.g. `pc1-stack` Caddy, `pc2-worker` dev-proxy).
  - Non-HTTP(S) ingress (SSH, WireGuard, custom TCP/UDP ports) is controlled by whatever service binds that port or receives DNAT/forwarded traffic.

### VPN hostnames: host Caddy -> per-stack Caddy (Windows)

- **Goal**: Host Caddy owns `80/443` and terminates TLS (`tls internal`) for `*.pc1.vpn` / `*.pc2.vpn`, then forwards to a stack-local Caddy which handles all internal routing.
- **Hostname convention**:
  - `<stack>.pc1.vpn` and `*. <stack>.pc1.vpn` route to the `pc1` stack ingress.
  - `<stack>.pc2.vpn` and `*. <stack>.pc2.vpn` route to the `pc2` stack ingress.
- **Upstream ports (examples)**:
  - `pc1-stack` stack Caddy: `127.0.0.1:18081` (published as `18081:80`)
  - `pc2-worker` stack Caddy: `127.0.0.1:19081` (published as `19081:80`)
  - `app-demo` stack Caddy: `127.0.0.1:${APP_DEMO_HTTP_PORT}` (published as `${APP_DEMO_HTTP_PORT}:80`)

### Production (idc1 / a1-idc1)
- **Front-end**: Caddy 2 running on the idc1 VM via systemd, using the configs under `sites/a1-idc1/config/Caddyfile*` which expose `idc1.surf-thailand.com` and `a1.idc1.surf-thailand.com` with automatic HTTPS handling.@sites/a1-idc1/config/Caddyfile#1-38@sites/a1-idc1/config/Caddyfile.remote#58-69
- **DNS**: `A` records for both hostnames point to `103.245.164.48`. Keep TTL ≤ 300s when rotating certificates so ACME challenges see updates quickly.
- **Provisioning workflow**:
  1. Install the official Caddy repo (`apt install -y debian-keyring debian-archive-keyring && curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg`, then `apt install caddy`).
  2. Copy the desired Caddyfile from `sites/a1-idc1/config/` to `/etc/caddy/Caddyfile` and reload via `sudo systemctl reload caddy`.
  3. Ensure `/var/www/{idc1,a1}` is readable by the `caddy` user (`sudo chown -R caddy:www-data /var/www/idc1 /var/www/a1`) so the ACME HTTP challenge files can be served.
- **Caddy validation loop**:
  1. Run `pwsh ./scripts/validate-caddy.ps1` (or add `-SkipFormat` if you only need validation). The script binds `sites/a1-idc1/config` into the official `caddy:2` image, runs `caddy fmt --overwrite`, and then `caddy validate`.
  2. MCP DevOps exposes the same helper via the `validate-caddy` workflow; invoke it before `deploy-a1-idc1` so the pipeline fails fast if the file is malformed.
  3. Once validation passes, deploy with `scripts/deploy-a1-idc1.sh` and reload the daemon (`ssh chaba@idc1 'sudo systemctl reload caddy'`).
- **Renewal**: handled automatically by Caddy’s built-in ACME client; check `journalctl -u caddy -f` during renewals.

> **Side notes & fixes**
> - We initially left UFW closed on ports 80/443 so Let’s Encrypt HTTP challenges failed. Fix: `sudo ufw allow 80,443/tcp`.
> - Our first deploy copied files as `root`, preventing Caddy (running as the `caddy` user) from reading `/var/www/a1`. Running `sudo chown -R caddy:www-data /var/www/a1` resolved the `permission denied` errors in `journalctl`.
> - We briefly enabled the ACME staging endpoint while testing (`acme_ca https://acme-staging-v02.api.letsencrypt.org/directory`) and forgot to revert, which produced “(STAGING)“ certificates. Removing the stanza and forcing `caddy reload` swapped us back to production certs.

### pc2 (WSL dev proxy)
- **Use case**: provide real HTTPS for local stacks exposed from WSL2 so Windows browsers stop warning during MCP/UI testing.
- **Certificate authority**: `mkcert` root installed in both Windows and the Ubuntu 24.04 WSL distribution. Run `mkcert -install` in PowerShell (to import into Windows trust) and again inside WSL (so CLI tools like curl trust it).@docs/system-inventory/pc2/stack-plan.md#45-67
- **Issuance workflow**:
  1. Choose a dev domain that resolves to localhost everywhere (we use `*.pc2.localtest.me` so DNS automatically points to `127.0.0.1`).
  2. Inside WSL: `mkdir -p ~/stacks/pc2-worker/dev-proxy/certs && cd ~/stacks/pc2-worker/dev-proxy/certs`.
  3. Issue the cert: `mkcert pc2.localtest.me *.pc2.localtest.me`.
  4. Reference the generated `pc2.localtest.me+2.pem`/`-key.pem` from the dev Caddy (or nginx) config. For Caddy we add:
     ```
     https://pc2.localtest.me {
       tls /home/tonezzz/stacks/pc2-worker/dev-proxy/certs/pc2.localtest.me+2.pem \
           /home/tonezzz/stacks/pc2-worker/dev-proxy/certs/pc2.localtest.me+2-key.pem
       reverse_proxy 127.0.0.1:3100
     }
     ```
  5. Restart the proxy container (`docker compose --profile mcp-suite restart dev-proxy`) so it picks up the files.
- **Sharing with Windows browsers**: export the mkcert root that lives in `%LOCALAPPDATA%\mkcert` and drop it into “Trusted Root Certification Authorities” in `certmgr.msc` for the `Local Computer` store. That keeps Chrome/Edge happy even though traffic terminates inside WSL.

> **Side notes & fixes**
> - Running `mkcert` only inside WSL meant Windows trusted nothing; Edge kept throwing `NET::ERR_CERT_AUTHORITY_INVALID`. Installing the root in Windows’ trust store fixed it.
> - Caddy’s container could not read the certs when we stored them on the Windows side (`/mnt/c/...`). Copying them into the WSL home directory and setting `chmod 600` allowed the `caddy` process to load the keys.
> - After resuming from sleep the WSL clock drifted, causing TLS handshakes to fail with `certificate has expired` even though the cert was new. `wsl --shutdown` (or `sudo hwclock -s`) re-synced the clock and the errors disappeared.

### Checklist
- Confirm DNS records + firewall rules (ports 80/443) before touching certificates.
- Keep `mkcert` roots versioned in `~/.config/mkcert` backups so new laptops can trust our dev domains immediately.
- Document any ACME outages (rate limits, staging certs) in `docs/system-inventory/<host>/YYYY-MM-DD.md` for future auditing.

## Standard WSL → SSH → idc1 template (unattended)
Use this pattern for any remote command to avoid PowerShell quoting issues (especially with characters like `@`, `{}`, and quotes).

```powershell
# Remote bash script (multi-line)
 $remote = @'
 set -euo pipefail
 echo "[REMOTE] host=$(hostname) user=$(whoami)"
 docker ps --format "table {{.Names}}\t{{.Image}}\t{{.Ports}}" | head
 '@

 # Encode so we don't fight nested quoting
 $b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes(($remote -replace "`r","")))

 # Execute on idc1 via WSL ssh (unattended)
 wsl bash -lc "printf %s '$b64' | base64 -d | /usr/bin/ssh -i ~/.ssh/chaba_ed25519 -o IdentitiesOnly=yes -o BatchMode=yes chaba@idc1.surf-thailand.com 'bash -s'"
 ```

 Notes:
 - This requires the key to exist inside WSL at `~/.ssh/chaba_ed25519` with `chmod 600`.
 - Prefer this over inline one-liners when the remote command contains quotes, braces, or Go-template strings like `{{.Names}}`.

 Always use this unattended WSL → SSH pattern for idc1 work:
 - `wsl bash -lc ...`
 - user: `chaba@idc1.surf-thailand.com`
 - key: `~/.ssh/chaba_ed25519`
 - options: `-o IdentitiesOnly=yes -o BatchMode=yes`

## CoreDNS + WireGuard DNS (idc1)
 This is the VPN DNS path used for `*.vpn` hostnames (e.g. `memory.idc1.vpn`).

 ### What runs where
 - **WireGuard server**: Docker container `idc1-wg-easy` (image `ghcr.io/wg-easy/wg-easy:latest`)
 - **DNS for VPN**: Docker container `idc1-wg-dns` (image `coredns/coredns:1.11.1`)
 - **Important**: `idc1-wg-dns` runs with `network_mode: container:<idc1-wg-easy-container-id>`
   - i.e. CoreDNS shares the network namespace with `wg-easy`, so it can bind the VPN-side DNS IP/port.

 ### CoreDNS configuration
 - **Corefile path on idc1 host**:
   - `/home/chaba/chaba/stacks/idc1-stack/config/coredns/Corefile`
 - **Corefile key block**:
   - `vpn:53 { hosts { ... } forward ... }`
 - **Record added for central memory**:
   - `10.8.0.1 memory.idc1.vpn`

 Current `vpn:53` hosts block should include:
 ```txt
 10.8.0.1 idc1.vpn
 10.8.0.11 pc1.vpn
 10.8.0.12 pc2.vpn
 10.8.0.1 memory.idc1.vpn
 ```

 ### Caddy exposure (VPN-only)
 - `memory.idc1.vpn` is reverse-proxied by Caddy to the memory service.
 - Caddy config lives in `stacks/idc1-stack/config/caddy/Caddyfile` and blocks non-VPN IPs:
   - allowlist: `10.8.0.0/24` and `127.0.0.1`

 ### Verification
 - **From a VPN client** (pc1/pc2/iOS): query the VPN DNS server:
   - `nslookup memory.idc1.vpn 10.8.0.1`
 - **On idc1**: CoreDNS logs confirm it answers:
   - `docker logs --tail 120 idc1-wg-dns | grep memory.idc1.vpn`
 - Note: `resolvectl query memory.idc1.vpn` on idc1 may fail because it uses `systemd-resolved` stub (127.0.0.53/54) and is not necessarily configured to forward `.vpn` to CoreDNS.

 ### Common gotcha: wg-easy must advertise the DNS server
 CoreDNS can be correct and still “not work” for clients if the client configs don’t set `DNS = 10.8.0.1`.

 - The intended setting is `WG_DEFAULT_DNS=10.8.0.1`.
 - In this repo, `stacks/idc1-stack/.env` is expected to contain:
   - `WG_DEFAULT_DNS=10.8.0.1`
 - If `docker inspect idc1-wg-easy` shows it still has `WG_DEFAULT_DNS=1.1.1.1`, recreate the service from the stack:
   - `cd /home/chaba/chaba/stacks/idc1-stack && docker compose --profile vpn up -d wg-easy`
 - After changing DNS, **clients must re-download / re-import** their WireGuard config from wg-easy for the DNS line to update.

 ### Split-tunnel AllowedIPs (wg-easy)
 wg-easy also controls what `AllowedIPs` appears in the downloaded client configs.

 Intended split-tunnel (VPN subnet only):
 - set: `WG_ALLOWED_IPS=10.8.0.0/24`
 - effect (client `[Peer]`): `AllowedIPs = 10.8.0.0/24`
 - note: clients must re-download / re-import after changing this.

 Current state (Dec 15 2025):
 - changed from full-tunnel (`0.0.0.0/0, ::/0`) to split-tunnel (`10.8.0.0/24`) via `stacks/idc1-stack/.env` and `docker compose --profile vpn up -d wg-easy`.

 ### VPN network config (authoritative)
 WireGuard subnet:
 - `10.8.0.0/24`
 - gateway / server IP: `10.8.0.1` (wg-easy `wg0`)

 wg-easy defaults (idc1):
 - `WG_PORT=51820`
 - `WG_DEFAULT_ADDRESS=10.8.0.x`
 - `WG_DEFAULT_DNS=10.8.0.1`
 - `WG_ALLOWED_IPS=10.8.0.0/24` (split tunnel)

 CoreDNS (VPN DNS):
 - container: `idc1-wg-dns` (CoreDNS)
 - DNS server IP (inside wg-easy netns): `10.8.0.1:53`
 - `.vpn` hosts records live in `/home/chaba/chaba/stacks/idc1-stack/config/coredns/Corefile`.

 Verification (client):
 - `ping 10.8.0.1`
 - `nslookup idc1.vpn 10.8.0.1`
 - `nslookup memory.idc1.vpn 10.8.0.1`

 Recovery note (important):
 - If `WG_ALLOWED_IPS`/`WG_DEFAULT_DNS` changes require recreating `wg-easy`, VPN DNS can stop responding if `wg-dns` is not recreated to re-attach to the wg-easy network namespace.
 - Fix:
   - `cd /home/chaba/chaba/stacks/idc1-stack && docker compose --profile vpn up -d --force-recreate wg-easy wg-dns`

### VPN stack quickstart (idc1)
Start/recreate VPN services:
- `cd /home/chaba/chaba/stacks/idc1-stack && docker compose --profile vpn up -d --force-recreate wg-easy wg-dns`

Verify (client):
- `nslookup idc1.vpn 10.8.0.1`
- `nslookup mcp0.idc1.vpn 10.8.0.1`
- `ssh chaba@idc1.vpn`
- `curl -sf http://mcp0.idc1.vpn:${MCP_DOCKER_PORT:-8340}/health`

## SSH over VPN (idc1.vpn)
`idc1.vpn` resolves to `10.8.0.1`, which is the `wg0` IP **inside** the `idc1-wg-easy` container.

Because host `sshd` is not bound to `10.8.0.1` (the host typically has no `wg0`), `idc1.vpn:22` must be forwarded from the wg-easy container to the host.

Default behavior:
- `idc1.vpn:22` is forwarded to host `sshd` using `iptables` DNAT rules applied by wg-easy on interface up (`WG_POST_UP` in `stacks/idc1-stack/docker-compose.yml`).

Notes:
- The forwarding target is `${WG_EASY_HOST_GW:-172.20.0.1}` (Docker host gateway as seen from inside the `idc1-wg-easy` container). If the Docker bridge gateway differs on your host, set `WG_EASY_HOST_GW` in `stacks/idc1-stack/.env`.

Recovery:
- If `ssh chaba@idc1.vpn` returns `Connection refused` after recreating/restarting `wg-easy`, recreate the VPN services so `WG_POST_UP` runs:
  - `cd /home/chaba/chaba/stacks/idc1-stack && docker compose --profile vpn up -d --force-recreate wg-easy wg-dns`
- Fallback (if you need to patch a running system without recreating containers):
  - `scripts/idc1-fix-mcp0-vpn.sh`

## Windows SSH key ACL fix
 When NTFS permissions prevent WSL/OpenSSH from using a private key (the “UNPROTECTED PRIVATE KEY FILE” error), run the following in an elevated PowerShell session. This consistently resets ownership and grants read-only access to the current user:

```powershell
$acct = "$env:COMPUTERNAME\$env:USERNAME"

takeown /F "C:\chaba\.secrets\pc1\chaba2\.ssh\chaba_ed25519"

icacls "C:\chaba\.secrets\pc1\chaba2\.ssh" /inheritance:r
icacls "C:\chaba\.secrets\pc1\chaba2\.ssh" /grant:r "$($acct):(OI)(CI)(RX)"

icacls "C:\chaba\.secrets\pc1\chaba2\.ssh\chaba_ed25519" /inheritance:r
icacls "C:\chaba\.secrets\pc1\chaba2\.ssh\chaba_ed25519" /grant:r "$($acct):(R)"
```

After running these commands, retry the SSH command from WSL.

## services_map.json metadata (optional)
`docs/services_map.json` can include additional optional metadata to help with operations/debugging without changing how stacks run:
- `hosts.<host>.repos`: repo checkout locations on that host
- `containers.<name>.source`: build/image origin (e.g. image name)
- `containers.<name>.runtime`: runtime constraints (e.g. `network_mode`, `cap_add`)
- `containers.<name>.notes`: short human notes (e.g. special routing/forwarding)

## System inventory (recommended)
As the repo grows, service inventory should live in per-host files under `docs/system-inventory/`:
- `docs/system-inventory/services_idc1.json`
- `docs/system-inventory/services_pc1.json`
- `docs/system-inventory/services_pc2.json`

Keep `docs/services_map.json` as a small index / compatibility layer that points to the per-host files (and optionally a compiled `hosts` map if older tooling requires it).

## Webtop UID/GID mapping (idc1-stack)
 LinuxServer `webtop` runs processes as user `abc` inside the container. To avoid permission issues when editing the repo bind mount (`/workspaces/chaba`), configure the container UID/GID to match the host user.

- `.env` (gitignored) should include:
  - `WEBTOP_PUID=1000`
  - `WEBTOP_PGID=1000`
- `stacks/idc1-stack/docker-compose.yml` maps these to LinuxServer `PUID/PGID` for `webtop`/`webtop2`.

Recreate `webtop2` (example):

```bash
cd /workspaces/chaba/stacks/idc1-stack
docker compose --profile mcp-suite up -d --force-recreate webtop2
```

Verification notes:
- `docker exec ... id` runs as **root** by default (so it will show `uid=0`).
- Verify the mapped user instead:

```bash
docker exec -it idc1-webtop2 id abc
docker exec -it --user 1000:1000 idc1-webtop2 id
```

## pc1-stack webtop sessions (multi-user / isolated)
pc1 keeps only the `mcp-webtop*` helpers for managing persistent webtop `/config` volumes (export/import). The Webtop UI containers are not part of `pc1-stack`.

### Sessions
- **mcp-webtop2**
  - config volume: `webtop2-config`
  - config API: `mcp-webtop2` on `http://pc1.vpn:8055`
- **mcp-webtop3**
  - config volume: `webtop3-config`
  - config API: `mcp-webtop3` on `http://pc1.vpn:8056`

### pc1-stack Caddy (VPN HTTPS, tls internal) — key workflow
pc1 runs Caddy as a Docker container (`pc1-caddy`) with an internal CA (`tls internal`) to provide HTTPS for VPN hostnames.

Important behavior:
- Editing `stacks/pc1-stack/Caddyfile` does **not** automatically reload the running container.
- After any Caddyfile change, run a reload:

```powershell
docker exec pc1-caddy caddy validate --config /etc/caddy/Caddyfile
docker exec pc1-caddy caddy reload --config /etc/caddy/Caddyfile
```

Shortcut:

```powershell
powershell -File scripts/pc1-caddy-reload.ps1
```

Via MCP DevOps (workflow):

```json
{
  "tool": "run_workflow",
  "arguments": {
    "workflow_id": "pc1-caddy-reload"
  }
}
```

Additional pc1 ops workflows (MCP DevOps):
- `pc1-caddy-status`
- `pc1-caddy-logs`
- `pc1-caddy-restart`
- `pc1-stack-status`
- `pc1-stack-up`
- `pc1-stack-down`

Notes:
- The Caddyfile is mounted read-only (`:ro`), so formatting inside the container (`caddy fmt --overwrite`) will fail. Format on the host if needed.
- Client browsers must trust Caddy's internal CA to avoid TLS warnings.

Security note:
- If any secret/token was ever pasted into a file or terminal output during setup, rotate it (treat it as compromised) and keep tokens only in env vars / `.secrets/` (never committed).
## Detects vision API (`/test/detects`)

- **Source layout**: UI lives in `sites/a1-idc1/test/detects/`; the Glama vision proxy/API is `sites/a1-idc1/api/detects/` with its `.env` (GLAMA_URL/KEY, model, prompt, etc.).@sites/a1-idc1/api/detects/src/server.js#1-184
- **Health probes**: `GET /health` on the API process reports `status`, `model`, and `glamaReady`. Caddy forwards `/test/detects/api/*` to whatever listens on port `4120` (@sites/a1-idc1/config/Caddyfile#17-27).
- **Model selection**: the backend reads `GLAMA_MODEL_VISION` for the default and `GLAMA_VISION_MODEL_LIST` (comma-separated) for alternates. The UI calls `GET /test/detects/api/models` to populate the dropdown and sends the chosen model with each `/analyze` request. Update both env vars + restart the service whenever we add/remove models (currently `gpt-4o-mini-2024-07-18` default + `gpt-4.1-2025-04-14` alt).

### Local/dev-host workflow
1. `cd sites/a1-idc1/api/detects && npm install`.
2. Run with PM2 using the bundled ecosystem file: `pm2 start ecosystem.config.cjs --env development`. PM2 home: `C:\Users\hp\.pm2`; manage via `pm2 list`, `pm2 logs detects-api`, `pm2 restart detects-api`.
3. Dev-host proxy (`http://127.0.0.1:3100/test/detects/*`) points to `http://host.docker.internal:4120` by default, so once the PM2 process is up you can test end to end.
4. **Hands-off preview (detects-only):** `powershell -File scripts/preview-detects.ps1` brings up Docker (if needed), installs pm2, launches the detects API, waits for `/health`, validates `http://dev-host.pc1:3000/test/detects/api/health`, and prints the preview URL.
5. **Full /test preview (chat + agents + detects):** `powershell -File scripts/preview-test.ps1` boots the dev-host container, starts the Glama/chat API (4020), agents API (4060), and detects API (4120) via PM2, verifies each `/health` plus the proxied dev-host endpoints, then confirms the `/test` landing page before printing `http://dev-host.pc1:3000/test/`.

> **Current state (Dec 6 2025)** – Detects API is running under PM2 on the Windows workstation only; production `a1.idc1` still needs its own daemon before the public URL returns data.

### Production runbook (a1.idc1 VM)
1. Sync `sites/a1-idc1/api/detects/` plus its `.env` to `/var/www/a1/api/detects` (or similar).
2. `cd` into that directory, `npm install --production`.
3. Option A: run via PM2 (`pm2 start ecosystem.config.cjs --env production && pm2 save && pm2 startup`). Option B: create a systemd unit (patterned after `glama.service`) that sets `WorkingDirectory`, exports the env file, and runs `/usr/bin/node -r dotenv/config src/server.js`. Enable + start it (`sudo systemctl enable --now detects.service`).
4. Confirm port `4120` is listening (`ss -ltnp | grep 4120`), then hit `https://a1.idc1.surf-thailand.com/test/detects/api/health`.
5. If Caddy returns 404, it means nothing is bound to `127.0.0.1:4120` on the VM—double-check the service status (`journalctl -u detects.service -f`).

Keep the doc updated when the production daemon is live (and capture unit files under `sites/a1-idc1/config/` for version control).
