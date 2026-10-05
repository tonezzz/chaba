# dispatch outcome — vcast-health-loop

## What changed

Built `scripts/ada/vcast-auto-health.py` — a chaba probe mirroring
`cms-auto-health.py` / `gev-auto-health.py` that turns cast-lane failures
on tony-dell into `vcast-auto-<lane>` kanban cards (review on failure,
auto-close to done on recovery, 12h priority escalation, glob-close of
retired-check cards). It runs inside the existing `kanban-sync.sh` tick
(15min), so no new job entry was needed — the tick's commit+push covers
its output.

Five lanes (all probed from tony-dell):

| slug | source | failure signal |
|---|---|---|
| `audit-cast` | systemctl | timer inactive / `Result!=success` / last run >15min (3 missed 5-min ticks) |
| `cast-browser-proxy` | systemctl + http :8799 | unit inactive or `GET /state` != 200 (socat -> tony-omen, so a dead omen backend opens the card too) |
| `yt-live-api` | systemctl + http :8791 | unit inactive or `GET /status` != 200 |
| `flap-check` | node `vcast-flap-check.mjs` | harness rc!=0; falls back to `~/CascadeProjects/chaba-tony-dell` when the running checkout lacks `ws`; one retry (fixed ports 13010/13991 can collide) |
| `lease` | http `/api/input-bridge/{capture,displays}` | active capture lease on a `connected:false` screen, lease >24h (`VCAST_LEASE_MAX_H`), or unparseable `since` |

Files touched:

- `scripts/ada/vcast-auto-health.py` (new)
- `scripts/ada/kanban-sync.sh` — added the lane + header comment
- `docs/ssot/kanban/ssot.kanban.yml` — kanban-sync lane role lists `vcast-auto-*`
- `docs/ssot/infrastructure/ssot.jobs.yml` — kanban-sync note updated
- `docs/ssot/jobs/vcast/2026-10-05-vcast-health-loop.yml` — job record
  (decisions, findings, verify runbook)
- `docs/ssot/kanban/cards/vcast-auto-{flap-check,yt-live-api}.yml` —
  done-state cards left by the live verification cycle

## Verified live on tony-dell

    systemctl --user stop yt-live-api
    python3 scripts/ada/vcast-auto-health.py
      -> FAIL yt-live-api; card vcast-auto-yt-live-api in review
         (note carried both is-active=inactive and :8791 conn-refused)
    systemctl --user start yt-live-api; sleep 3
    python3 scripts/ada/vcast-auto-health.py
      -> card auto-closed to done

`yt-live-api` was picked for the kill test because `/status` showed it
idle (transcoding=false); `cast-browser-proxy` feeds the 60s panel-cast
path so it was left alone. All 5 lanes currently green.

## Findings worth knowing

- flap-check's first run crashed rc=1 with only a Node version banner on
  stderr (likely a bind race on the harness's fixed ports); rerun passed
  7/7. The probe now retries once and surfaces the first real error line
  in the card note.
- Escalation inherits the sibling lanes' date-granular quirk: a card
  opened after 12:00 local is `priority: high` immediately. Same wart as
  cms/gev lanes — noted in the job record, fix uniformly if it bothers.
- `ssot-validate-all.mjs`: all touched/created files valid; the single
  repo-wide error is pre-existing and unrelated
  (`jobs/infrastructure/2026-10-05-precleanup-unmerged-guard.yml` YAML
  syntax error from another session).
- If the kanban-sync worktree should run flap-check against its own copy
  instead of falling back to chaba-tony-dell: `npm ci` once in
  `~/CascadeProjects/chaba-kanban-sync/stacks/web/input-bridge`.

## Rollout note

The lane becomes live the next time `origin/master` contains this commit
and `kanban-sync.timer` ticks (it ff-pulls `chaba-kanban-sync` first).
Nothing else to install — no new units, no secrets, all probes are
loopback/systemctl.
