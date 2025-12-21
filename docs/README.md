# Chaba infrastructure notes

## SSL quick reference

### Production (idc1 / a1-idc1)
- **Front-end**: Caddy 2 running on the idc1 VM via systemd, using the configs under `sites/a1-idc1/config/Caddyfile*` which expose `idc1.surf-thailand.com` and `a1.idc1.surf-thailand.com` with automatic HTTPS handling.@sites/a1-idc1/config/Caddyfile#1-38@sites/a1-idc1/config/Caddyfile.remote#58-69
- **DNS**: `A` records for both hostnames point to `103.245.164.48`. Keep TTL ≤ 300 s when rotating certificates so ACME challenges see updates quickly.
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

## Webtops / Windsurf runtime caching

Windsurf is installed at runtime (pinned version) inside each webtop session container, but downloads are cached in a shared Docker volume so new sessions do not re-download the `.deb`.

- **Shared cache volume**: `WEBTOPS_WINDSURF_CACHE_VOLUME` (default: `webtops_windsurf_cache`)
- **Mount path inside session**: `WEBTOPS_WINDSURF_CACHE_MOUNT_PATH` (default: `/windsurf-cache`)
- **Runtime installer cache root** (inside the session container): `WINDSURF_CACHE_ROOT=/windsurf-cache`

This keeps the "stable tag" workflow (image points to `webtops-windsurf-runtime:stable`, version is pinned via env var) while allowing fast session creation after the first download on a host.

### Checklist
- Confirm DNS records + firewall rules (ports 80/443) before touching certificates.
- Keep `mkcert` roots versioned in `~/.config/mkcert` backups so new laptops can trust our dev domains immediately.
- Document any ACME outages (rate limits, staging certs) in `docs/system-inventory/<host>/YYYY-MM-DD.md` for future auditing.

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
