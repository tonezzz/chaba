# Dispatch outcome — nest-edge-vision (phases 1–4, 2026-10-07)

## What was done

Phase 1's `/apps/eye/` page already existed on master (e236153 — MediaPipe
efficientdet_lite0_int8 in-browser, `?src=me|cam:|snap:|test`,
`?bench=N`). This session fixed what was missing or broken across the
remaining phases:

- **MDDB write lane (the page was silently failing).** eye.js posted to
  `https://idc03.taila0626a.ts.net/mddb/v1` — no such edge mount exists
  (probed: 404/405). Added route `eye-mddb` to `ssot.routes.yml` + a
  custom block in `render-routes.py`: `POST /apps/eye-mddb/v1/add` →
  `mddb /v1/add`, tailnet-identity-gated, add-only surface. Regenerated
  `stacks/web/Caddyfile` (byte-diff = the two new blocks) and
  `apps/routes.json`.
- **xmeye channels (phase 1 gap).** There is no xmeye HLS — the existing
  proxy is the vms-snap/camwall pipeline. Added `?src=snap:<zone>/<key>`
  (camwall last-good thumbs, covers `vms-noble-*` and every pulled zone)
  and `?src=vms:<channel>` (fresh ~10s captures via new same-origin
  `/apps/vms-snap/*` → mn01 :8377 proxy). Fixed a latent bug: snapImg was
  never inserted into the DOM, so snap sources drew boxes over blackness.
- **Phase 2 — bench CMS.** `scripts/eye/bench-edge-cms.py` scans
  `ada-ha-scenario-reports` `bench/edge-*`, aggregates per device (UA
  labels) + model, renders the cms-page-standard layout + PIL fps-trend
  PNG to `apps/reports/bench-edge-trend.png`, dedup-hash-gated, writes
  `ada-cms-pages/bench-edge` (written live — currently the empty-state
  page with usage instructions). `systemd/bench-edge-cms.{service,timer}`
  hourly at :23. `--dry-run` verified with fixture rows incl. chart.
- **Phase 3 — cast lane.** `scripts/eye/cast-eye.sh`:
  `screen N` → input-bridge nav (the display's own browser runs the
  detector — true edge); `tv [ws]` → opens fullscreen Chrome on
  tony-omen workspace N over ssh, then `nav tony-omen:workspace:N`
  (cast-desktop@0 → HLS → camera.play_stream → tony_tv_cast). Found and
  documented: `screenlive:workspace:N`'s `cast-desktop@1`/`camera.desktop_1`
  wiring predates the cast move to omen (omen has only :0) — the script
  uses the omen lane. Runbook: `docs/runbooks/eye-cast.md`.
- **Phase 4 — ada_look.** Write side shipped: `?pub=N` rewrites
  `ada-ha-scenario-reports/eye/latest` every N s
  (`{ts, src, model, detections[{cls,score,box}], ua}`). The tool lives in
  ada-pi (out of this worktree) — ready-to-apply manifest + tool_runner
  sketch in `docs/ssot/jobs/eye/2026-10-07-nest-edge-vision.yml`
  (`handoff_ada_look`), filed as card `ada-look-tool` (backlog).
  Read-only contract; actions stay behind existing confirm-gated tools.

## Results / caveats

- `bench-edge` CMS page is live in MDDB (empty-state until first bench
  POST lands). reports-index regen failed server-side ("remote closed
  connection" on the index add — likely the ongoing mddb binlog/embed
  issues; page write itself succeeded; regen retries hourly via timer).
- **Deploy pending** (needs merge + caddy reload): eye-mddb and vms-snap
  routes return 404 until then; eye.js changes need the public dir sync.
  Listed under `needs_approval` in the job doc along with the systemd
  timer install, the ada-pi ada_look implementation, and the first live
  TV cast (`cast-eye.sh tv 4` hijacks omen workspace 4).
- iOS `src=me` stays a real-seat/Safari path — vcast nav iframes lack
  `allow="camera"` (deferred deliberately).

## How to verify (after merge + deploy)

```bash
# page + detector
open https://tony-dell.taila0626a.ts.net/apps/eye/?src=test&bench=30
# MDDB write lane (needs tailnet identity)
curl -X POST https://tony-dell.taila0626a.ts.net/apps/eye-mddb/v1/add -d '{...}'
# xmeye
open .../apps/eye/?src=vms:Guard%20View&pub=10
# cast to lab screen
scripts/eye/cast-eye.sh screen 6 "src=test&bench=60&pub=10"
# then: ada-ha-scenario-reports eye/latest + bench/edge-* rows exist;
# bench-edge-cms.py picks them up; "ada, what do you see" once the
# ada-pi tool lands
```

Commit: `b598b5a` on `dispatch/20261007-141922-phases-1-apps-eye-page-ada-pi-`.
