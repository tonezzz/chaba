# Dispatch outcome — vcast-ha-screens (sync tony-ha/www/vcast-screens-card.js screen list)

## What was wrong

The card renders whatever `GET /api/input-bridge/displays` returns, and the
live registry currently contains **zombie entries**: screens 2 (`headless-2`)
and 4 (`headless-4`) report `connected:true` but `last_seen` is ~18h stale —
the headless displays died and the deployed input-bridge on idc03 still runs a
pre-ux-flow `server.mjs` (its `/displays` returns only `{screens,pending}` —
no `lifecycle`/`health`/`released`/`timeline` fields the repo version emits),
so nothing sweeps or marks them dead. The card listed them as cast targets.

## What changed (commit `83dbb4d98b` on `dispatch/20261124-150148-sync-tony-ha-www-vcast-screens`, rebased onto origin/master)

- `stacks/tony-dell/tony-ha/www/vcast-screens-card.js` — new `_liveScreen()`
  gate: a screen is a cast target only when the relay's `lifecycle` is
  `connected|idle|playing` (new server shape), or — for the old shape the
  live relay still serves — `connected:true` **and** `last_seen` fresher
  than 150s (server `STALE_SEEN_MS`=120s; displays heartbeat ~30s). Dead
  entries render collapsed under "⚠ N offline registry entries — dead
  displays, not cast targets" with last-seen age and the same
  Sweep/Release actions (extracted to `_sweepBtn()`/`_releaseBtn()`).
- `stacks/tony-dell/tony-ha/www/vcast-screens-card-check.mjs` — new
  DOM-stub regression check (14 assertions, 3 fixture cases) plus `--live`
  mode that renders against the real relay and prints the target/offline
  split.
- `docs/ssot/jobs/vcast/2026-11-24-vcast-screens-card-live-filter.yml` —
  job record with findings + promotion notes.

## Verification (all on michael-dev / read-only live probes — nothing deployed to tony-ha)

- `node vcast-screens-card-check.mjs` — all checks pass (old shape, new
  lifecycle shape, pending/empty states).
- `node vcast-screens-card-check.mjs --live` against the real relay:
  **2 cast targets listed (#6 vcast-real-6, #7 vcast-real-7)**; dead
  headless-2/4 collapsed into the offline section.
- Headless Chrome render of the actual file: identical result.
- Staged: `scp` → `idc02:~/.config/michael-dev/www/vcast-screens-card.js`
  (michael-dev moved idc03→idc02 2026-10-26; serves plain HTTP on
  `100.123.163.11:8124`). `/local/vcast-screens-card.js` → 200, md5
  `15ee4a3d…` matches repo. No lovelace resource references it on
  michael-dev — asset-only staging.
- tony-ha still serves the **old** 267-line card; repo is now 395 lines.
  Promotion = copy to tony-ha www (+ ada-ha if registered there) and bump
  the `?v=` resource — **requires Tony's explicit approval**, not done.

## Follow-ups worth carding

- Redeploy `stacks/web/input-bridge/server.mjs` on idc03 + restart
  `input-bridge.service` — the live relay predates the whole ux-flow
  rework, which is why zombie entries exist at all.
- The two dead headless displays (screens 2/4) can be Sweep/Release'd from
  the card once promoted, or via `POST /sweep` now.

lessons:
- "Sync the screen list" for this card means filtering zombie registry
  entries client-side — the card has no hardcoded list; `last_seen` is the
  only honest liveness clock when the relay is old.
- The live input-bridge on idc03 is stale vs repo (no lifecycle/health in
  /displays) — always check the deployed server's response shape before
  assuming repo behavior.
- michael-dev moved idc03→idc02 on 2026-10-26 and serves plain HTTP on
  `100.123.163.11:8124` (idc02 :8124 tailnet IP); `idc03:8124` refuses.
- A ~60-line DOM stub + `new Function` makes HA custom cards node-testable
  without a browser; `--live` mode then verifies against the real endpoint.
