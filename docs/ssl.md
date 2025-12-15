# SSL quick reference

## Production (idc1 / a1-idc1)
- **Front-end**: Caddy 2 running on the idc1 VM via systemd, using the configs under `sites/a1-idc1/config/Caddyfile*` which expose `idc1.surf-thailand.com` and `a1.idc1.surf-thailand.com` with automatic HTTPS handling.@sites/a1-idc1/config/Caddyfile#1-38@sites/a1-idc1/config/Caddyfile.remote#58-69
- **DNS**: `A` records for both hostnames point to `103.245.164.48`. Keep TTL <= 300s when rotating certificates so ACME challenges see updates quickly.
- **Provisioning workflow**:
  1. Install the official Caddy repo (`apt install -y debian-keyring debian-archive-keyring && curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg`, then `apt install caddy`).
  2. Copy the desired Caddyfile from `sites/a1-idc1/config/` to `/etc/caddy/Caddyfile` and reload via `sudo systemctl reload caddy`.
  3. Ensure `/var/www/{idc1,a1}` is readable by the `caddy` user (`sudo chown -R caddy:www-data /var/www/idc1 /var/www/a1`) so the ACME HTTP challenge files can be served.
- **Caddy validation loop**:
  1. Run `pwsh ./scripts/validate-caddy.ps1` (or add `-SkipFormat` if you only need validation). The script binds `sites/a1-idc1/config` into the official `caddy:2` image, runs `caddy fmt --overwrite`, and then `caddy validate`.
  2. MCP DevOps exposes the same helper via the `validate-caddy` workflow; invoke it before `deploy-a1-idc1` so the pipeline fails fast if the file is malformed.
  3. Once validation passes, deploy with `scripts/deploy-a1-idc1.sh` and reload the daemon (`ssh chaba@idc1 'sudo systemctl reload caddy'`).
- **Renewal**: handled automatically by Caddy's built-in ACME client; check `journalctl -u caddy -f` during renewals.

> **Side notes & fixes**
> - We initially left UFW closed on ports 80/443 so Let's Encrypt HTTP challenges failed. Fix: `sudo ufw allow 80,443/tcp`.
> - Our first deploy copied files as `root`, preventing Caddy (running as the `caddy` user) from reading `/var/www/a1`. Running `sudo chown -R caddy:www-data /var/www/a1` resolved the `permission denied` errors in `journalctl`.
> - We briefly enabled the ACME staging endpoint while testing (`acme_ca https://acme-staging-v02.api.letsencrypt.org/directory`) and forgot to revert, which produced "(STAGING)" certificates. Removing the stanza and forcing `caddy reload` swapped us back to production certs.

## pc2 (WSL dev proxy)
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
- **Sharing with Windows browsers**: export the mkcert root that lives in `%LOCALAPPDATA%\mkcert` and drop it into "Trusted Root Certification Authorities" in `certmgr.msc` for the `Local Computer` store. That keeps Chrome/Edge happy even though traffic terminates inside WSL.

> **Side notes & fixes**
> - Running `mkcert` only inside WSL meant Windows trusted nothing; Edge kept throwing `NET::ERR_CERT_AUTHORITY_INVALID`. Installing the root in Windows trust store fixed it.
> - Caddy's container could not read the certs when we stored them on the Windows side (`/mnt/c/...`). Copying them into the WSL home directory and setting `chmod 600` allowed the `caddy` process to load the keys.
> - After resuming from sleep the WSL clock drifted, causing TLS handshakes to fail with `certificate has expired` even though the cert was new. `wsl --shutdown` (or `sudo hwclock -s`) re-synced the clock and the errors disappeared.

### Checklist
- Confirm DNS records + firewall rules (ports 80/443) before touching certificates.
- Keep `mkcert` roots versioned in `~/.config/mkcert` backups so new laptops can trust our dev domains immediately.
- Document any ACME outages (rate limits, staging certs) in `docs/system-inventory/<host>/YYYY-MM-DD.md` for future auditing.
