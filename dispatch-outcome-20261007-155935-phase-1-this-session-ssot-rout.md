# dispatch outcome — edge-route-registry phase-1 (re-verify)

## What the dispatch asked

Phase 1 of card `edge-route-registry`: `ssot.routes.yml` with the full
dell-edge inventory, `render-routes.py` -> `stacks/web/public/apps/routes.json`
+ validation, and `ada-voice`/`ada-chat` cards resolving ws via routes.json.

## What was found

Phase 1 (and phase 2a + the health lane) were already complete and merged
into this worktree's base:

- `docs/ssot/infrastructure/ssot.routes.yml` — 46 routes, 30 services,
  4 edges (tony-dell-web, mn01-web, vps-public, idc03-serve).
- `scripts/render-routes.py` — emits `apps/routes.json` and validates
  (dup ids, shadow ordering, non-tailnet-IP upstreams). A fresh `build()`
  is identical to the committed `routes.json` modulo the timestamp.
- `stacks/web/public/apps/routes.json` — served live at
  `http://localhost/apps/routes.json` (200); `ada-tony.ws` resolves to
  `wss://idc03.taila0626a.ts.net/apps/ha/ada-tony/ws`.
- `ada-voice-card.js` / `ada-chat-card.js` — resolution order is
  `ws_url` config -> `/local/routes.json` -> literal fallback (verified
  in source).
- `stacks/web/Caddyfile` is byte-identical to `render-routes.py --caddy`
  output; `route-health.json` served live (200).

## What changed

One real fix this session (`scripts/check-routes.py`): running the health
sweep from a linked git worktree produced 5 false failures — the
static-route check looked for content dirs (jev-bench, yt-live,
walldance-live, chaba-h3, board) that are untracked/mounted and only
exist in the live checkout. Now, when `REPO/.git` is a file (worktree),
a missing static root reports `ok=None` (skipped) instead of failing.
Live-checkout semantics are unchanged — a genuinely missing dir still
fails.

## Result

- `python3 scripts/check-routes.py` in the worktree: 31 ok / 0 failing /
  15 skipped, exit 0 (was 31/5/10, exit 1).
- `card-pipeline.py edge-route-registry --api http://127.0.0.1:8787`:
  verify=pass (5/5 expected_goals now pass from a worktree — previously
  `route-health-clean` could only pass on the live host), audit=pass.
  Run artifact: `reports/ci/edge-route-registry-20261007-160710.json`.
- Trail: `docs/ssot/jobs/infrastructure/2026-10-07-edge-route-registry-worktree-verify.yml`.

## How to verify

```
python3 scripts/render-routes.py --check          # 46 routes, 18 shadow warnings (expected)
python3 scripts/render-routes.py --caddy && diff -q stacks/web/Caddyfile stacks/web/Caddyfile.generated
python3 scripts/check-routes.py                    # 0 failing, exit 0
curl -s http://localhost/apps/routes.json | jq .routes.ada-tony.ws
```

## Still open (per card spec)

- Phase 2b: mn01 + VPS edges consume the registry.
- Phase 3: cloudflared tunnel evaluation (registry as ingress config).
