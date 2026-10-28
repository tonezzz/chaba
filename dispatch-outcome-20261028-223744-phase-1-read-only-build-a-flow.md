# Dispatch outcome — Phase 1 Node-RED DevNest visual map

Card: `node-red-devnest-visual-map` · Runner: idc02 · 2026-10-28

## Result: LIVE

The Phase-1 read-only observe flow is **deployed and emitting**:
`DevNest observe map` tab added to the existing Node-RED on tony-dell
(flow id `4071a36a3e3ca21e`, additive `POST /flow` — the demo tab was not
touched). It writes CMS page **`devnest-visual-map`** every 5 min:
<https://idc03.taila0626a.ts.net/cms/#/devnest-visual-map>

14 specialist facts: board-api health, kanban stats, dispatch queue
(queued/running/stale-claims/runners), 4 JEV lane /health probes
(idc03:8778 gate, idc02:8777, omen:8777+8778), ollama-on-omen, LiteLLM
liveliness, ada-nest queue heartbeat (via mirror file), ops staleness,
runner-host snapshot, mcp-health, HA house-pulse. Report renders the
card's mental model (cards → queue → JEV → lanes/runners → GPU/Colab →
verify) plus the raw specialist table and the Phase-2 contract
(allowlisted `queue|hold`/`request` behind confirmation, never
shell/restart/delete/deploy — documented, not wired).

## Bonus fix found on the way

`nodred-live-demo` was frozen since 2026-10-13 — root-caused to TWO
drifts in the deployed demo tab: POST went to mddb `:11023` (the
`ada-cms-pages` collection moved to the CMS fork `:11027` in the 10-13
mddb split), and the board-api/HA URLs had been hand-edited to dead
tony-dell-local endpoints (`127.0.0.1:8787`, `tony-dell:8123`). Patched
the deployed tab in place — the page is green again for the first time
in 15 days.

## Changes in this worktree

- `stacks/tony-dell/node-red/flows-devnest-map.json` — the flow (34 nodes)
- `scripts/ops/nest-queue-health.py` — light ada-nest queue snapshot →
  `~/var/chaba/health/nest-queue-status.json` (the dir already
  RO-mounted into the container; rclone can't run inside it)
- `systemd/nest-queue-health.{service,timer}` — declared, **not armed**
- `stacks/tony-dell/node-red/flows-cms-live-report.json` — :11023→:11027
- `docs/ssot/jobs/devnest/2026-10-28-node-red-devnest-map.yml` — job doc
- `docs/ssot/apps/ssot.apps.node-red.yml` — flow files registered

On tony-dell (session artifacts): one-shot
`~/var/chaba/health/nest-queue-status.json` landed + flow backup at
`~/var/chaba/health/nodered-flows-backup-predevnest.json` (rollback:
`DELETE /flow/4071a36a3e3ca21e` on 127.0.0.1:1880).

## Surfaced live signal

Map flagged 2 stale dispatch claims >24h:
`jack-opencode-cloudflare-prep-idc02` (27h) and
`fix-cms-publish-page-slug-argument-missi-96152a` (40h) — reported in
card comms, no action taken.

## Open ask (board request raised)

Arm `nest-queue-health.timer` on tony-dell to keep the queue heartbeat
fresh — the landed snapshot ages honestly in the report ("snap Nm old")
until then.

## Verify

- Page: <https://idc03.taila0626a.ts.net/cms/#/devnest-visual-map>
- `curl -s http://127.0.0.1:1880/apps/node-red/flow/4071a36a3e3ca21e`
  on tony-dell → the deployed tab
- Mirror file: `~/var/chaba/health/nest-queue-status.json`
- Flow JSON parses + all function bodies compile (checked with node18)
- Not pushed; branch `dispatch/20261028-223744-phase-1-read-only-build-a-flow`
