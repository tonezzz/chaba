---
title: Tailscale Rollout Plan for Chaba
description: Step-by-step plan to install Tailscale and update SSOT/health check configs for stable remote access
tags: [tailscale, vpn, networking, ssot, remote-access, mobile]
created: 2026-08-13
updated: 2026-08-14
status: completed
---

# Tailscale Rollout Plan for Chaba

## Goal

Replace dynamic-IP and `.local` mDNS reliance for remote/mobile access with a Tailscale mesh VPN, then update the project's single-source-of-truth (SSOT) and health check files to reflect the new stable hostnames.

## Current State

- `tony-omen` is already joined to the tailnet at `100.75.102.88`.
- `tony-dell` was installed and authenticated on 2026-08-14 at `100.68.142.13` (Tailscale 1.102.2).
- Home profile still works with `.local` hostnames (`192.168.1.0/24` LAN, mDNS).
- Mobile profile has been updated to use the Tailscale tailnet hostname `tony-omen`.
- `ssot.mysystem.mobile.yml` marks VPN/Tunnel setup as `done`.
- `ssot.mysystem.home.yml` now tracks the tailnet IPs for both workstations.
- `stacks/web/public/ssot.health.mobile.yml` and `docs/ssot/infrastructure/ssot.health.yml` reference the Tailscale mobile profile.

## Target State

- All devices that need remote access are joined to the same tailnet.
- `tony-omen` is reachable via a stable Tailscale hostname (e.g., `tony-omen` or `tony-omen.tailXXXX.ts.net`).
- SSOT mobile profile and health checks use the Tailscale name instead of dynamic IPs or `tony-omen.local`.
- `.windsurfrules` hostname guidance is updated to define when to use `.local` vs Tailscale names.

## Phase 1 — Install and Verify Tailscale

### On `tony-omen` (Ubuntu)

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
sudo systemctl enable --now tailscaled
```

Check status:

```bash
tailscale status
tailscale ip -4
```

### On mobile/remote devices

Install the Tailscale app, sign in with the same account, and accept the device in the admin console.

### Validate peer-to-peer connectivity

From a remote device:

```bash
tailscale ping tony-omen
```

## Phase 2 — Choose Hostname and IP Strategy

Decide on one of the following:

1. **Magic DNS** (easiest): use `tony-omen` (short name inside tailnet) or `tony-omen.tailXXXX.ts.net`.
2. **Tailscale IP** (stable, human-unfriendly): use the `100.x.x.x` address assigned to `tony-omen`.
3. **Custom machine name**: rename the device in the Tailscale admin console to `tony-omen` if it is not already.

Recommendation: use the short Magic DNS name `tony-omen` inside the tailnet for services that are protected by the tailnet, and keep `tony-omen.local` for the home LAN profile.

## Phase 3 — Prepare `tony-omen` Services

1. Verify Caddy and any non-Docker services listen on all interfaces or the Tailscale interface:
   - `stacks/web/Caddyfile` / Docker Caddy container: should bind to `0.0.0.0` or at least `100.x.x.x` and `127.0.0.1`.
   - If `llama-router` (port `8001`), `postgres` (port `5432`), or other ports are bound to `127.0.0.1`, rebind them to `0.0.0.0` or the specific Tailscale IP.
2. Confirm no new ports need opening in the firewall; Tailscale uses outbound UDP and can punch through NAT.
3. Test service reachability over the Tailscale IP:

```bash
# from a remote device
curl http://$(tailscale ip -4 tony-omen):8080/api/health
curl http://tony-omen:8080/api/health
```

## Phase 4 — Update SSOT and Health Check Files

### `docs/ssot/ssot.mysystem.mobile.yml`

- Mark the `VPN/Tunnel` item under `Dynamic IP Solutions` as `status: done`.
- Add a `Tailscale` profile next to `Home Profile` and `Mobile Profile`:
  - `text`: Stable tailnet access using `tony-omen` name.
  - `config`: `ssot.mysystem.mobile.yml`.
  - `health_config`: `ssot.health.mobile.yml`.
  - `switch_method`: Connect via Tailscale app, then use `tony-omen`.
- Update the `tony-omen` workstation `current_access`:
  - `text`: `Accessible via Tailscale as tony-omen`.
- Update the `Services` and `Access & URLs (Mobile)` sections from `http://[current-ip]:...` to `http://tony-omen:...`.

### `stacks/web/public/ssot.health.mobile.yml`

- Replace `http://tony-omen.local:...` with `http://tony-omen:...` for all `url` fields (or the chosen full Magic DNS name).
- Update the `hostname_resolution` recovery note:
  - Replace the note about `tony-omen.local` resolving to `172.20.10.7`.
  - Add: "On mobile, connect to Tailscale first; use `tony-omen` instead of `tony-omen.local`."
- Keep the `vpn_required` recovery action but update the text to reference Tailscale specifically.

### `docs/ssot/infrastructure/ssot.health.yml`

If this is the source copy, mirror the same changes made to `stacks/web/public/ssot.health.mobile.yml`.

## Phase 5 — Update Hostname Standards

### `.windsurfrules`

Add a Tailscale clause to the existing hostname usage standards:

```markdown
- Use `.local` hostnames on the home LAN.
- Use Tailscale hostnames (`tony-omen`) or Magic DNS (`tony-omen.tailXXXX.ts.net`) for remote/mobile access.
- Use `100.x.x.x` Tailscale IPs only where hostnames cannot be resolved.
```

## Phase 6 — Validate and Smoke Test

1. From the mobile/remote device on the tailnet:

```bash
tailscale status
tailscale ping tony-omen
```

2. Test a few key endpoints:

```bash
curl http://tony-omen:8080/api/health
curl http://tony-omen:8001/health
curl http://tony-omen:8080/apps/health-check/
```

3. Run the health check mobile configuration:

```bash
# from the health-check project directory or via the configured health-check runner
./health-check stacks/web/public/ssot.health.mobile.yml
```

4. Run the project validation tools:

```bash
skill ssot-validate
```

## Phase 7 — Optional Enhancements

- **Subnet routes**: advertise the `192.168.1.0/24` home subnet from `tony-omen` so remote devices can reach non-Tailscale LAN devices.
- **Exit node**: make `tony-omen` an exit node for secure mobile internet routing.
- **Headscale**: if the cloud coordination server is not acceptable, migrate to a self-hosted Headscale instance later.

## Phase 8 — Public Funnel Access and Active Connections (Delivered)

Tailscale Funnel was enabled and configured so the Chaba web UI is reachable from the public internet.

- **Public URL (Funnel)**: `https://tony-omen.taila0626a.ts.net/`
- **Magic DNS (tailnet)**: `http://tony-omen:8080`
- **Home LAN**: `http://tony-omen.local:8080`

### Delivered components

1. **Funnel landing page** — `stacks/web/public/apps/tailscale-funnel/index.html` explains the three access paths (home, tailnet, public Funnel).
2. **Network options banner** — `stacks/web/public/apps/index.html` now shows the three URLs at the top of the apps directory.
3. **Active connections panel** — embedded in the Funnel landing page; fetches `/api/tailscale/connections` every 5 s and lists online, non-infrastructure peers with hostname, IP, OS, active/idle, and direct/relayed status.
4. **Connections API** — `stacks/web/tailscale-connections-server.py` serves `tailscale status --json` over HTTP at `/api/tailscale/connections`, filtered to real devices (excludes Tailscale infrastructure/ingress nodes).
5. **Caddy routes** — `stacks/web/Caddyfile` added:
   - `handle @funnel_root` for the Funnel root landing page.
   - `handle_path /apps/tailscale-funnel/*` for the same page under `/apps`.
   - `handle /api/tailscale/connections` reverse-proxy to `host.docker.internal:9010`.
6. **Systemd service** — `~/.config/systemd/user/tailscale-connections.service` makes the API persist across reboots and restart on failure.
7. **Health check integration** — `stacks/web/public/ssot.health.mobile.yml` now has a `tailscale-funnel` HTTP service and `funnel_unreachable` recovery actions.
8. **Workflow check** — `workflows/monitoring/universal-health-check.yml` now has a `tailscale_check` block that reports `tailscale status`, `tailscale ping`, and Funnel reachability.

### Verify

```bash
# Public page and API
curl -I https://tony-omen.taila0626a.ts.net/
curl -s https://tony-omen.taila0626a.ts.net/api/tailscale/connections | python3 -m json.tool

# Systemd service
systemctl --user status tailscale-connections.service
```

## Phase 9 — Tailscale Client Auto-Updates (Selected)

Enable automatic Tailscale client updates on all nodes so security patches and bug fixes apply without manual intervention.

- Command on Linux: `tailscale set --auto-update`
- Package-manager alternative: keep the `tailscale` package on the stable repo and enable the OS’s unattended-upgrades mechanism.
- Status: **selected for implementation**.

### Why

Keeps the tailnet secure and reduces operational toil on each node. For a single-node setup this is low risk; for multiple nodes it should be combined with a maintenance window or update notifications.

### Risks

- An update could introduce a breaking change on a remote/headless host.
- Mitigation: test updates on `tony-omen` first and keep a local console/SSH backup path.

## Future (not now)

- **Exit node** — make `tony-omen` an exit node for secure mobile internet routing. Useful, but not required until you want to route all remote traffic through home.
- **Headscale** — self-hosted Tailscale control plane. Only if you want to remove the cloud coordination server dependency.

## Rollback

1. Disconnect or uninstall Tailscale:

```bash
sudo tailscale down
# or
sudo apt remove tailscale
```

2. Revert `ssot.health.mobile.yml`, `ssot.mysystem.mobile.yml`, and `.windsurfrules` changes via git.
3. Fall back to DDNS or current-IP access until the issue is resolved.

## Related Files

- `docs/kb/hardware-tony-omen-software-env.md` — current software state on `tony-omen`.
- `docs/ssot/ssot.mysystem.mobile.yml` — mobile profile and access URLs.
- `stacks/web/public/ssot.health.mobile.yml` — mobile health check endpoints.
- `docs/overview/hostname-enforcement-strategy.md` — hostname usage policy.
- `docs/architecture/wireguard-architecture.md` — alternative self-managed VPN.
