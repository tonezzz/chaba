# Moving HA and Ada public URLs to idc01 — pros & cons (Devin)

Date: 2026-09-23 · Author: Devin · Status: analysis only, no changes made

## Current state (verified live)

| Thing | Public URL today | Exposure | Backend |
|---|---|---|---|
| Ada Tony | `https://mn01.taila0626a.ts.net/apps/ha/ada-tony/` | **Funnel (public)** on mn01 → mn01 Caddy :8080 → uvicorn :8002 | mn01 |
| Ada Michael | `https://mn01.taila0626a.ts.net/apps/ha/ada-michael/` | Funnel on mn01 → :8003 | mn01 |
| tony-ha | `https://tony-dell.taila0626a.ts.net:8123` | **serve, tailnet only** → HA :8123 | tony-dell |
| michael-dev | `https://tony-dell.taila0626a.ts.net:8124` | serve, tailnet only → :8124 | tony-dell |
| michael-ha | Nabu Casa URL | public via Nabu Casa | michael-ha |
| idc01 | `https://idc01.taila0626a.ts.net` (:8001), `:8443` (:8004), `:8444` (:8502), `:8445` (:5055) | serve, **tailnet only — no Funnel enabled** | idc01 |

"Move to idc01" would mean: run `tailscale serve`/`funnel` on idc01 proxying back over
WireGuard to mn01:8002/8003 (Ada) and tony-dell:8123 (HA). The hostname necessarily
changes to `idc01.taila0626a.ts.net` — ts.net names are per-node and cannot be kept.

## Pros

1. **Stable public entrypoint decoupled from backend host.** Today's Ada URL contains
   `mn01` — if the backend ever moves hosts, the public URL breaks. An idc01 edge makes
   the URL backend-agnostic: repoint internally without touching clients.
2. **Smaller public surface on home nodes.** The Funnel ingress lives on the VPS, not on
   mn01/tony-dell. Home machines only ever see tailnet-authenticated traffic from idc01.
   (This also fixes the current oddity where tony-dell's funnel `/` exposes the bserver
   dashboard publicly.)
3. **Ingress survives home workstation problems.** tony-dell has documented crash/swap/
   Devin-restart issues; an edge on a datacenter VPS keeps accepting connections and can
   fail cleanly instead of vanishing.
4. **Foundation for a real domain later.** idc01 has a real public IP — a future
   `ada.example.com` + Caddy ACME can replace ts.net naming and funnel's shared ingress
   without another client-visible URL change.
5. **Consolidation.** One place to audit what's publicly reachable, instead of funnel
   configs spread across mn01 and tony-dell.

## Cons

1. **Extra hop on a latency-sensitive path.** Ada carries realtime audio over its WS.
   Chain becomes client → Tailscale funnel ingress → idc01 → WireGuard → mn01:8002 →
   Gemini. Every ms of added RTT lands in the voice loop.
2. **New hard dependency.** idc01 down = all moved URLs dead even when home is healthy.
   Today Ada public needs only mn01; after the move it needs mn01 **and** idc01.
3. **Origin change = re-pair everything.** Ada's TOFU device keys live in browser
   localStorage per origin. `mn01…` → `idc01…` orphans every stored key — the iPhone
   admin PWA, voice PWAs, and any redeemed devices must re-enter keys / re-redeem.
   Old QR redeem links embed the old host and stop working.
4. **PWA/bookmark churn.** Installed PWAs are origin-scoped; all need reinstalling.
   chaba-admin iframes, dashboards, and docs referencing the old URLs need updates.
5. **HA gains almost nothing.** HA is tailnet-only today — any tailnet device already
   reaches `tony-dell…:8123` directly. Serving it via idc01 adds a hop for zero benefit.
   Making HA *public* through an idc01 funnel is a different question entirely: it puts
   the HA login page on the open internet (brute-force surface, needs `trusted_proxies`,
   `ip_ban`, MFA, external_url rework). Not recommended as a side-effect of a URL move.
6. **Proxy-chain complexity.** funnel → idc01 proxy → tailnet → backend complicates
   X-Forwarded-For, websocket upgrade headers, and HA's `use_x_forwarded_for` config.
7. **idc01 resource/traffic costs.** It's a small rented VPS — Ada audio + any proxied
   media now flow through it (bandwidth, CPU for TLS). Its egress already goes through
   Cloudflare WARP with documented quirks.
8. **Another config to maintain.** serve/funnel + reverse proxy on idc01 isn't in
   SSOT/IaC today; drift risk until documented.

## Recommendation

- **HA: don't move.** Keep tailnet-only on tony-dell. If public HA access is ever
  needed, evaluate it as its own security project (or use Nabu Casa like michael-ha).
- **Ada: reasonable but low urgency.** Move only if the goal is a host-independent
  public URL or isolating funnel off mn01. If you do it, plan it as a migration:
  announce the origin change, re-issue/re-redeem device keys, update the pair page,
  chaba-admin iframes, and SSOT in one pass — then keep `mn01…` funnel alive briefly as
  a redirect window.
- **If you want one thing from this:** putting a stable public edge on idc01 pays off
  most when combined with a real domain; as a pure ts.net hostname swap, the churn
  cost (re-pairing every device) roughly equals the benefit.
