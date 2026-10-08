# dispatch-outcome — lab-cf-kv-claw-channel

## Result: built + locally verified; live deploy BLOCKED on token scopes

The card's pre-req ("add Workers KV + Workers Scripts Edit scope to the
cfut_ token") is only half done. Verified against the CF API with the
live token from tony-omen (`~/.config/secrets/cloudflare.env`):

| Scope | Status |
|---|---|
| Workers Scripts Edit (account) | ✅ present (scripts list OK) |
| Zone Read (surf-thailand.com) | ✅ present |
| Workers KV Storage Edit | ❌ auth error on namespace list |
| Workers Routes Edit (zone) | ❌ "No access to the specified resource" |
| Zone DNS Edit | ❌ auth error on dns_records |
| Workers R2 Storage | ❌ auth error (optional — R2 artifacts) |

Also found: **dell/idc01/idc02 `cloudflare.env` hold a stale `cfat_`
token the API rejects outright** (code 1000). The valid `cfut_` lives
only on tony-omen. I did not modify any secret files — flagged on the
card.

Board request raised with the exact dashboard clicks; `needs-input.txt`
written to the task dir.

## Deliverables (this worktree, branch dispatch/20261008-120820-…)

- `edge/claw-channel/worker.js` — ~90-line Worker, zero deps:
  `GET /<agent>` → `cmd:<agent>`, `GET /digest/<n>` → `digest:<n>`,
  `GET /report/<a>` → `report:<a>:latest` (all unauthenticated);
  `POST /report|cmd|digest/…` gated by `X-Ingest-Key` (wrangler secret,
  constant-time compare, JSON-only ≤1 MiB, wrong key → 403). Optional
  `CLAW_R2` binding writes report artifacts.
- `edge/claw-channel/wrangler.toml` — template; deploy.sh renders
  `wrangler.deploy.toml` (gitignored) with the real namespace id/host.
- `scripts/claw-publish.py` — reads board-api `/cards` (fallback repo
  `cards.json`), emits `{generated, counts, cards:[{id,title,column}]}`
  with titles scrubbed of hostnames (ssot.values.yml hosts + statics),
  IPv4, ts.net/.local, and paths. Card ids kept verbatim — they are the
  join key and slug-scrubbing collides. Writes `digest:board` via CF
  API, or `--via-ingest <url>` through the worker for hosts without CF
  creds.
- `stacks/edge/claw-channel/` — `stack.yml`, `README.md`, `deploy.sh`
  (idempotent: scope preflight → `wrangler kv namespace create` →
  secret put INGEST_KEY → AAAA `claw → 100::` proxied → wrangler deploy
  → seed `cmd:demo` → verify curls).
- `docs/ssot/infrastructure/ssot.routes.yml` — `cf-surf` edge entry.
- `docs/ssot/jobs/infrastructure/2026-10-08-claw-channel-cf-kv.yml` —
  full trail.

## Design decision: hostname

`edge.surf-thailand.com` resolves publicly to idc02's real IP — the
record is DNS-only, so a Workers route there can never fire, and
flipping it proxied would reroute the whole `*-ha` CNAME family through
CF. Used dedicated workers-only host `claw.surf-thailand.com` instead
(AAAA `100::` + proxied). Spec allowed "e.g.".

## Verified

- Worker logic: node harness with Map-backed fake KV — **14/14 pass**
  (cmd/digest/report round-trips, 403 wrong+missing key, 400 bad JSON,
  404 unknown paths, `/claw`-prefixed and bare paths, R2 write).
- `claw-publish.py --dry-run`: 250 cards, ~29 KB, title leak scan clean.
- `bash -n deploy.sh`, `yaml.safe_load` on stack/job yml, SSOT validator
  clean for touched files (2 pre-existing unrelated YAML errors remain).
- NOT verified (blocked): live deploy, anonymous GET, real 403, phone
  read. Re-run path: `stacks/edge/claw-channel/deploy.sh` then the
  README verify block — one command after scopes land.
