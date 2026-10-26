# Dispatch outcome — installer v2 keyless enroll endpoint

**Card:** fleet-installer-v2 · **Runner:** idc02 · **Branch:** dispatch/20261026-070642-installer-v2-keyless-enroll-en (commit d2f84b75, not pushed)

## What was delivered

**1. `/enroll` endpoint — LIVE and verified on the public edge.**

The "existing /enroll contract" was recovered from the live
`/usr/local/bin/stick-announce.sh` on tony-macbook: it POSTs MDDB
`/v1/add` writing `kind=ops-event type=host_online` into
`ada-ha-events-tony` with meta `{instance:tony, host, lan_ip,
tailnet_ip, ts, written_by}`.

- `stacks/web/input-bridge/server.mjs` — new `POST /enroll` accepting
  `{hostname|host, lan_ip, tailnet_ip, role}`: upserts the node registry
  (`nodes.json`, persisted next to displays.json) and emits the
  identical ops-event doc (`written_by=input-bridge-enroll`). `GET
  /nodes` reads the registry. Guards: hostname/IPv4 validation, 4KB body
  cap, 5-min host+tailnet dedupe, 30 posts/IP/hour.
- Deployed to idc03 `~/apps/input-bridge/server.mjs` on the **live
  base** (205b2212 + enroll) — repo HEAD's unverified vcast UX-flow
  redesign was deliberately not shipped; repo HEAD carries the same
  enroll block so the next deploy keeps it. Backup:
  `server.mjs.bak-20261026`.
- `idc03 ~/.config/caddy/Caddyfile` — `handle /enroll* → 127.0.0.1:3010`
  on **both** `api.` and `app.` site blocks (the flat `app.` block was
  restructured — its `respond @notinstall 404` would have 404'd
  `/install`). Validated + `caddy reload`; backup
  `Caddyfile.bak-20261026`.
- `stacks/web/public/install` (deployed to edge `/data/install`) — v2:
  after tailscale up it POSTs hostname/lan/tailnet/role to
  `api.surf-thailand.com/enroll` (`ENROLL_URL` overridable; failure is
  warn-only).

**2. Cloudflare token — could NOT be provisioned (real gate).**

- `cfat_` (the DNS-capable token) is **dead on every slot** — idc02/idc03
  `verify` returns Invalid API Token; all secrets-backup bundles hold the
  same dead fingerprint. `cfut_` (omen/dell) is alive but Workers-only
  (no DNS read or write). wrangler OAuth can't write DNS.
- CF does not allow minting API tokens via API (user+account POSTs →
  9109). Creation is dashboard-only.
- Raised board request
  `need-a-new-dns-capable-cloudflare-token-15edf9` asking Tony to mint
  `Zone > DNS > Edit` on surf-thailand.com and drop it in a
  `cloudflare.env` slot. **`scripts/ops/cf-dns-upsert.sh`** (new,
  idempotent) then creates `A app.surf-thailand.com → 157.85.102.125
  (proxied)` in one command — the `app.` site block is already wired, so
  `/install` + `/enroll` go live on it immediately.

## Verified

- `POST https://api.surf-thailand.com/enroll` → `200 {ok,event:true}`,
  doc landed in `ada-ha-events-tony` (`ops-host-enroll-*`, correct meta).
- `GET https://api.surf-thailand.com/install` → 200, serves v2 script.
- `http://127.0.0.1:3010/health` → `nodes:2`; `/displays` intact (5
  screens). Local smoke test on idc02 passed all assertions.
- `app.surf-thailand.com` on :80 → 308 → https (site block correct;
  cert+DNS pending).

## SSOT trail

`docs/ssot/jobs/infrastructure/2026-10-26-installer-v2-enroll-endpoint.yml`;
route note in `ssot.routes.yml`; cfat_ death + pending-token note in
`ssot.secrets.yml`; `stacks/idc03/input-bridge/stack.yml` state/ports
updated.

## Remaining (Tony gate)

Mint DNS-capable CF token → drop into `~/.config/secrets/cloudflare.env`
(idc02) → run `scripts/ops/cf-dns-upsert.sh` → `app.surf-thailand.com`
resolves and serves /install + /enroll.
