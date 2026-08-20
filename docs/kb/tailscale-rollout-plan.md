---
category: operations
---

# Tailscale Rollout Plan for Chaba

## Tailscale Spec Reference

| Item | Value |
|---|---|
| Tailnet account | `tonezzzz@` |
| `tony-omen` tailnet IPv4 | `100.75.102.88` |
| `tony-dell` tailnet IPv4 | `100.68.142.13` |
| `kk-macbook` tailnet IPv4 | `100.124.59.112` |
| `tony-omen` Magic DNS (FQDN) | `tony-omen.taila0626a.ts.net` |
| `tony-dell` Magic DNS (FQDN) | `tony-dell.taila0626a.ts.net` |
| `kk-macbook` Magic DNS (FQDN) | `kk-macbook.taila0626a.ts.net` |
| Home LAN | `192.168.1.0/24` |
| `tony-omen` LAN mDNS | `tony-omen.local` |
| `tony-dell` LAN mDNS | `tony-dell.local` |
| Public Funnel URL | `https://tony-dell.taila0626a.ts.net/` |
| Funnel server listen port | `8082` |
| Funnel proxy target | `http://127.0.0.1:8082` |
| Active connections API | `https://tony-dell.taila0626a.ts.net/api/tailscale/connections` |
| API backend | `~/chaba-funnel/funnel-server.py` on `0.0.0.0:8082` |
| Systemd user service | `~/.config/systemd/user/chaba-funnel.service` |
| Health check file | `stacks/web/public/ssot.health.mobile.yml` |
| Workflow block | `workflows/monitoring/universal-health-check.yml` (`tailscale_check`) |
| Auto-update command | `tailscale set --auto-update` |

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

## See also

- [Tailscale Rollout Initial](tailscale-rollout-initial.md)
- [Tailscale Rollout Maintenance](tailscale-rollout-maintenance.md)
- [Tailscale Rollout Public](tailscale-rollout-public.md)
- [Tailscale Rollout Ssot](tailscale-rollout-ssot.md)
