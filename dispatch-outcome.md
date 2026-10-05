# gev-health-loop — gev-auto-* health loop

## What changed

- `scripts/ada/gev-auto-health.py` (new) — probes the GEV stack on tony-dell
  and opens a `gev-auto-<check>` kanban card in `review` on failure,
  auto-closing to `done` on recovery (lifecycle mirrored from
  `cms-auto-health.py`/`logs-kanban.py`, incl. 12h escalation and
  glob-close of retired-check cards). Five lanes:
  - `page` — `GET http://127.0.0.1/apps/gev/` via Caddy must return 200
  - `ws` — websocket upgrade `ws://127.0.0.1/apps/gev-live/ws?remote=1`
    must return 101 + valid `Sec-WebSocket-Accept` (raw stdlib socket; the
    `remote=1` flag registers a passive client so no Gemini Live session
    is opened — the probe is free)
  - `api` — `GET http://127.0.0.1:4173/<bogus>` on gods-eye-view-api; any
    HTTP < 500 = alive (server has no health route; unknown paths 404
    fast, real routes proxy slow external calls)
  - `bridge` — `systemctl --user is-active gev-gemini`
  - `api-service` — `systemctl --user is-active gods-eye-view-api`
- `scripts/ada/kanban-sync.sh` — runs the new probe each tick after
  `logs-kanban`; the existing `git add docs/ssot/kanban/cards/` step
  commits and pushes its output.
- `docs/ssot/kanban/ssot.kanban.yml` — kanban-sync lane role now lists
  `gev-auto-*`.
- `docs/ssot/infrastructure/ssot.jobs.yml` — kanban-sync note updated.
- `docs/ssot/jobs/gev/2026-10-05-gev-health-loop.yml` — job trail with
  decisions and the D-state startup-stall finding.
- `docs/ssot/kanban/cards/gev-auto-{bridge,ws}.yml` — done-state cards
  left by the live verification cycle (real incident records, same as
  existing `cms-auto-*` done cards).

## Verification (ran live on tony-dell)

1. Healthy run: `0 failing, 0 cards written` — no cards.
2. `systemctl --user stop gev-gemini` + run → `gev-auto-bridge` card in
   review (`is-active -> failed`) AND `gev-auto-ws` in review (caddy
   502 — the downstream lane).
3. `systemctl --user start gev-gemini` + run → `gev-auto-bridge` closed
   to done; `gev-auto-ws` stayed open ~90s because the fresh bridge
   process sat in D state before binding :8789 (unit read `active` the
   whole time — the ws lane catching this is why the multi-lane design
   matters), then closed on the next run.
4. `python3 -m py_compile`, `bash -n kanban-sync.sh`, and
   `ssot-validate-all.mjs` (1180 files, 0 errors) all clean.

## Notes / follow-ups

- The loop activates in production once this branch merges and the
  `chaba-kanban-sync` worktree ff-pulls it (≤15min); no separate deploy —
  the timer already runs `kanban-sync.sh`.
- Escalation quirk inherited verbatim from the sibling lanes: card age is
  measured from midnight of `updated`, so afternoon incidents open at
  `priority: high` immediately. Documented in the job file; fix uniformly
  across cms-auto-*/logs-auto-*/gev-auto-* if desired.
- Finding worth a look later: fresh gev-gemini container starts twice
  took ~90-100s in D state (`folio_wait_bit_common`) before the bridge
  bound its ports. Root cause not chased — possibly fuse-overlayfs page-in
  latency.
