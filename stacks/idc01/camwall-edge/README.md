# camwall-edge — tailnet thumbnail edge

Caddy serving static camera thumbnails for `/apps/camwall/*` — bound to the
host's tailnet IP on :8380 only (never a public interface).

## Files

- `camwall-edge.container` — quadlet; `PublishPort` is pinned to the host's
  tailnet IP — on a move, render it: `PublishPort=$(tailscale ip -4):8380:8380`
- config: `~/.config/camwall-edge/Caddyfile` (mounted ro)
- state: `~/.local/share/camwall/` — thumbnail files (regenerable; rsync
  only if you want history)

## Move

Copy Caddyfile + thumbnails, render the quadlet with the target's tailnet
IP, `daemon-reload && start`. Consumers reach it at
`<host>.taila0626a.ts.net:8380` — update callers if the hostname changes.
