# Dispatch outcome — cloudflare-setup (attempt 2)

## What this was

Stale re-dispatch of kanban card `cloudflare-setup`, already `column: done`
since 2026-10-03 (commit 8839c3fc42). Attempt 1 left no trail — card comms
show only automated runner-agent "defers" noise; the likely cause is the
prompt's hardcoded `http://127.0.0.1:8787` board-api, which does not exist
on this host (idc02). Working endpoint: `https://idc03.taila0626a.ts.net:10000`.

## Verified (by surface, not memory)

- `api.surf-thailand.com` → CF anycast IPs, HTTP 200, `<title>Ada</title>`,
  `cf-ray`/`server: cloudflare` headers. Note: the A record now points at
  **idc03** (157.85.102.125), not idc01 as the Oct-3 note says — repointed
  after idc01's retirement; outcome equivalent.
- `edge.surf-thailand.com` → DNS-only → 45.136.236.190 (idc02) as recorded.
  It is a CNAME anchor for the `*-ha` family; direct TLS to `edge.` SNI
  fails by design (no site block) — not a fault.
- Zone map (27 records, via CF API): ~25 proxied, 2 DNS-only. Live curls:
  `tony-ha/kk-ha/michael-dev/cms/monitor` → 302 (CF Access), `boards/status/apex`
  → 200, `www` → 308, `api` → 200.

## Optional item: SSL=strict — audited, NOT flipped

- `GET /zones/4feb4a36…/settings/ssl` → `value: full`, `editable: true`
  (idc02 `cloudflare.env` token has zone-settings read; write scope
  unverified — never probed on prod).
- **Blocker:** idc02 `caddy-edge` uses `tls internal` on every site block
  (~20 names) → origins present "Caddy Local Authority" certs, untrusted.
  Strict would return 526 for the whole edge.
- Ready: idc03 `api.`/`app.` serve valid LE certs. Needs work:
  `idc03.` (no cert at SNI — likely stale record), `idc01.` (origin dead —
  idc01 retired, stale record), `wiki.*` CNAME→`wiki.h3.gizmo-thailand.com`
  (origin LE SANs cover only `*.h3.gizmo-thailand.com` — strict outcome
  depends on CF's SNI choice for proxied CNAMEs).

## Deliverables

- Trail: `docs/ssot/jobs/infrastructure/2026-11-24-cloudflare-ssl-strict-audit.yml`
- Follow-up card: `cf-ssl-strict-migrate-idc02-edge-origin-3fa959` (OPS-0027,
  backlog) — cert migration paths (CF Origin Cert vs LE http-01-only),
  stale-record pruning, flip + verify procedure.
- Card comms posted on `cloudflare-setup` via board-api.

## How to verify

```
dig +short api.surf-thailand.com        # CF anycast IPs
curl -sI https://api.surf-thailand.com/ # 200, server: cloudflare
curl -s https://idc03.taila0626a.ts.net:10000/cards | jq '.cards[] | select(.id=="cf-ssl-strict-migrate-idc02-edge-origin-3fa959")'
```

No infrastructure was changed; zone remains SSL=Full.

lessons:
- board-api is not on 127.0.0.1:8787 on job hosts — use https://idc03.taila0626a.ts.net:10000.
- CF zone SSL mode is all-or-nothing: one tls-internal origin blocks strict for every proxied hostname.
- `tls internal` in a Caddyfile is invisible until you check origin certs — consumer 200s via CF Full hide it.
- GET zone settings returning editable:true is a plan flag, not token write scope — don't probe writes on prod.
