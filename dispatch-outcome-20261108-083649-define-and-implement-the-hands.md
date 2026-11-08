# dispatch outcome — hands-off-waiting-card-procedure (KNB-0928), re-dispatch verification

## Summary

This card was already fully implemented by the earlier dispatch
`20261108-081116-define-and-implement-the-hands` (checkpoint commit
`266070f4d`, merged into this worktree's base). This session re-verified
every spec element against the live tree rather than re-implementing —
no new code changes were needed.

## Verified against spec

- **Queue execution vs auto-close separation** — `scripts/board/waiting_cards.py`
  is the canonical gate: `action.type ∈ {dispatch,script,container}`,
  explicit `target_host`, autonomy envelope, declared artifact + verifier,
  no open requests, declared recoverability, preflight. R3/R4 → never
  autonomous in every gate mode.
- **Recoverability classes R0–R4** — declared in
  `docs/ssot/infrastructure/ssot.devin-autonomy.yml` `waiting_cards:`;
  enforced by the gate and the single-file twin in
  `scripts/board/runner-agent.py`.
- **Preflight** — kill switch, deploy-lock flock, disk floor, queue
  capacity, R2 backup freshness/proof, stale heartbeat, push credentials.
  Wired into `kanban-dispatch.py` (pass-level freeze) and runner-agent
  `_capacity_reason`.
- **Stop conditions** — stale heartbeat, missing artifact, verifier
  failure, wrong host, dirty/unmerged worktree, spend cap, open request.
- **Model-report independent review** — `scripts/ada/kanban-act.py`
  holds `report:`/`model_report:` cards unless `auto_done_when` includes
  `verified_true` or `git_merged`.
- **Telegram lifecycle** — `notify_lifecycle()` posts start/finish/fail/
  stalled via board-api `/publish`; kanban-dispatch `_notify`/`_flush_notify`
  and runner-agent `_notify` wired.
- **Dry-run + daily report** — `--dry-run` flags on both CLIs;
  `scripts/board/unattended-report.py` renders digest + Telegram milestone;
  `ssot.jobs.yml` + rendered `systemd/generated/idc03/chaba-unattended-report.{service,timer}`.
- **Rollback/kill switch** — `/tmp/no-kanban-dispatch` (also
  `KANBAN_WAITING_GATE=off` / `RUNNER_WAITING_GATE=off`).
- **1/2/3-day readiness checklist** — in `ssot.devin-autonomy.yml`
  `waiting_cards.readiness_checklist` (day1 done; strict-mode flip pending
  day-3 drill).
- **No parallel queue** — gate extends kanban-act-loop/kanban-dispatch/
  runner-agent; `docs/ssot/jobs/kanban/2026-11-08-hands-off-waiting-cards.yml`
  is the runbook; `docs/ssot/jobs/kanban/2026-10-08-kanban-act-loop.yml`
  carries the followup pointer.
- **Five read-only pilots** — `docs/ssot/kanban/cards/unattended-pilot-*.yml`;
  all 5 evaluate **ELIGIBLE** this session (all checks true).

## Verification run this session

- `python3 -m unittest tests.board.test_waiting_cards` — 25/25 OK
- `python3 -m unittest tests.board.test_kanban_act` — 18/18 OK
- `waiting_cards.py --board` — 2 queued cards evaluated → both HOLD
  (missing declared artifact/verifier/recoverability — correct under
  pre-contract cards; warn mode does not block claims)
- `waiting_cards.py --preflight` — kill_switch=false, deploy_lock=false,
  disk_free≈121GB ≥ 2GB floor
- `unattended-report.py --dry-run` — full digest renders, nothing written
- 5/5 pilot cards ELIGIBLE via `--evaluate`

## Remaining (day-2/3 checklist items, not dispatch work)

- Live end-to-end pilot run after merge+deploy (queue one
  `unattended-pilot-*` card).
- Flip `KANBAN_WAITING_GATE`/`RUNNER_WAITING_GATE` warn→strict after the
  day-3 kill-switch drill + recoverability backfill.
- runner-agent is single-file deploy — updated file must be copied to each
  runner host.
- R2 backup-freshness producer not yet wired (`WAITING_BACKUP_PROOF` /
  `backup_fresh=True` env) — followup noted in the job runbook.

## How to verify

`python3 -m unittest tests.board.test_waiting_cards`,
`python3 scripts/board/waiting_cards.py --board`,
`python3 scripts/board/waiting_cards.py --evaluate docs/ssot/kanban/cards/unattended-pilot-health-probe.yml`,
`python3 scripts/board/unattended-report.py --dry-run`.
