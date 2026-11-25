# edge-upstream audit — serve mounts + caddy upstreams vs live listeners

**Status:** deployed (card `edge-upstream-dead-port-audit`, job
`audit-edge-upstreams` on con01, hourly `*:41`). Report nodes:
`edge-upstreams/<host>` under `reports/edge-upstreams/`.

## Why (2026-11-18 incident)

tony-omen `tailscale serve` proxied `https://tony-omen.taila0626a.ts.net:8125`
to `127.0.0.1:8125` — a dead port. The tony-ha container actually listens on
`:8123`. caddy-edge on idc02 `reverse_proxy`s
`ada-ha.surf-thailand.com` to that serve port → the whole public vhost 502'd.
Fix was `tailscale serve --bg --https=8125 http://127.0.0.1:8123`.

Neither watchdog caught it because each only checks one layer:

- `check-routes.py` — declared routes on the `tony-dell-web` edge (registry-driven, localhost probes).
- `check-serve-config.py` — declared `<host>-serve` mounts vs `ssot.routes.yml`, on the one host it runs on.
- `ssot.health` http checks — end-to-end surfaces only (and :8125 had no entry).

The blind spot: **observed edge bindings** — what serve/caddy actually point
at, on every host, whether or not the registry remembers them.

## What the audit does

`scripts/audit-edge-upstreams.py` (read-only):

1. **tailscale serve drift** — `tailscale serve status --json` per host
   (background `Web`/`TCP` sections + `Foreground` sessions). Every handler
   `Proxy` target and `TCPForward` target is checked:
   - loopback (`127.0.0.1`, `localhost`, `::1`) → port must appear in the
     host's own `ss -ltn` table on a loopback-covering bind
     (`127.0.0.1`/`*`/`0.0.0.0`/`[::]`); a port bound only on the tailnet IP
     still fails (loopback clients refused);
   - `http+unix://` → socket in `ss -lxn`;
   - remote `http(s)://host:port` / `host:port` → GET from the runner,
     expect non-5xx;
   - `Path` (static roots) → dir exists on the host.
2. **caddy `reverse_proxy` upstreams** — per host, parses
   `~/.config/caddy/Caddyfile` (host-net edges: idc02, idc03), plus
   `~/web-srv/caddy/Caddyfile` and `~/.config/camwall-edge/Caddyfile`
   (slirp-net containers — their `127.0.0.1` upstreams are intra-container
   and marked `skipped`, not checked). Every upstream grouped per vhost;
   loopback → host listener check; remote → GET expecting non-5xx;
   container-net names (`frigate:5000`) → podman/docker inspect.

Statuses: `ok` / `dead` (nothing there) / `degraded` (answers but broken:
HTTP ≥500, TLS mismatch) / `skipped` (unverifiable-by-design). Exit 1 on any
dead or degraded row.

## Usage

```bash
python3 scripts/audit-edge-upstreams.py --all            # whole fleet, table
python3 scripts/audit-edge-upstreams.py --host idc02     # one host
python3 scripts/audit-edge-upstreams.py --all --json     # machine output
python3 scripts/audit-edge-upstreams.py --all --write    # artifacts + metas
                                                        # (reports/edge-upstreams/)
python3 scripts/audit-edge-upstreams.py --all --write --ship --alert
                                                       # the deployed form:
```

`--ship` rsyncs `reports/edge-upstreams/` to the served checkout
(`$CHABA_EDGE_SHIP`, default `idc03:CascadeProjects/chaba-tony-dell/reports/
edge-upstreams/`) — the remote-pushback contract so `edge-upstreams/<host>`
nodes stay fresh on the fleet report. `--alert` files one deduped board-api
`/inbox` entry per failing surface (state `~/var/chaba/edge-upstream-alerts.
json`, 24h repeat suppression).

## Reading findings

Row shape: `{host, surface, mount, upstream, status, evidence}`.

- `serve:<fqdn>:<port>` — a tailscale serve mount (mount = path or `-` for
  whole-port / `fg:<id>` = foreground session)
- `serve-tcp:<port>` — a raw TCPForward
- `caddy:<vhost>` — a `reverse_proxy` line in a Caddyfile (mount =
  `file:line`)

Fix is one of: start/repair the backend, repoint the binding
(`tailscale serve --bg --https=<port> <new-target>` or edit the Caddyfile +
`systemctl --user reload caddy-edge`), or drop the stale mount/vhost.

## First-sweep findings (2026-11-18 baseline)

Flagged by the first live run — real dead bindings, owner call whether the
backend should come back or the edge should drop:

- `tony-omen serve :8444 -> 127.0.0.1:9005` (ha-live, inactive) — also dead
  as `100.75.102.88:9005` in web-srv and 502 through `http://:8444` on the
  idc02 shadow edge. `ssot.health.home.tailscale.yml ha-live` already
  probes it.
- `michael-dev.surf-thailand.com -> https://idc02.taila0626a.ts.net:8124`
  — TLS mismatch: :8124 is michael-dev plain-HTTP on the tailnet IP; the
  serve `:8124` mount the route registry expects was never added/is gone.
  Fix = `tailscale serve --bg --https=8124 http://127.0.0.1:8124` on idc02
  or repoint the upstream to `http://`.
  **RESOLVED 2026-11-25** (card michael-dev-migrate-mn01): instance moved
  idc02 -> mn01; upstream now `https://mn01.taila0626a.ts.net:8124` and
  mn01 runs `tailscale serve --bg --https=8124 http://127.0.0.1:8124`.
  Root cause of the dead serve mount: a podman `PublishPort` on the
  tailnet-IP :8124 (added 2026-11-24) conflicts with serve's bind — the
  quadlet now publishes :8124 on 127.0.0.1 only.
- `web-srv -> frigate:5000` — container-net name, no frigate container on
  idc02 (the /frigate/* route 502s; likely never re-pointed after the
  2026-10-19 web origin migration off tony-dell).
