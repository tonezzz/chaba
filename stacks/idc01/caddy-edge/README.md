# caddy-edge — public edge on idc01

Caddy on the VPS public interface, :80/:443 — reverse proxy for the public
domains (Cloudflare/ DNS point at this host's public IP) and ACME issuance.
Separate from `camwall-edge` (tailnet-only thumbnail edge).

## Files

- `caddy-edge.container` — quadlet, `Network=host`
- config: `~/.config/caddy/Caddyfile` (mounted ro)
- data: `~/.config/containers/caddy/{data,config}` — certs + ACME state

## Move

1. rsync `~/.config/caddy/Caddyfile` and `~/.config/containers/caddy/` to the
   target (certs carry over; Caddy re-issues if they don't).
2. Install quadlet, `systemctl --user daemon-reload && start caddy-edge`.
3. Repoint DNS/CF at the target's public IP — ACME re-validates per-domain.
4. Cutover order matters: start the target edge before repointing DNS if you
   want zero-downtime; either way, old host should keep serving until TTLs
   drain.
