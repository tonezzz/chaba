# dispatch outcome — hands-off-waiting-card-procedure (KNB-0928)

## What changed

The spec layer (`waiting_cards:` in `ssot.devin-autonomy.yml`) already
existed from a prior session; this dispatch implemented the enforcement,
reporting, and validation layers — extending kanban-act-loop/DevNest, no
parallel queue.

**New code**
- `scripts/board/waiting_cards.py` — canonical gate: `evaluate(card, env,
  push_probe)` returns eligible/never/reasons/checks covering action.type
  ∈ {dispatch,script,container}, explicit target_host/host, autonomy ≤
  max_autonomy, declared artifact+verifier, no open requests, declared
  recoverability, preflight (kill switch, deploy-lock flock, disk floor,
  queue capacity, R2 backup freshness/proof, stale heartbeat), push
  credentials for dispatch repos. R3/R4 → `never=True` in every mode.
  CLI: `--evaluate`, `--board`, `--preflight`. `notify_lifecycle()` posts
  start/finish/fail/stalled via board-api `/publish`.
- `scripts/board/unattended-report.py` — daily digest: preflight state,
  queue snapshot, per-card gate verdicts, today's activity, metrics →
  `reports/unattended-<date>.md` + one Telegram milestone. Read-only.
- `tests/board/test_waiting_cards.py` — 25 tests.

**Wired in**
- `scripts/board/kanban-dispatch.py` — pass-level preflight (kill switch,
  deploy lock, disk <2GB freezes all claims); per-card gate
  (`KANBAN_WAITING_GATE=off|warn|strict`, default **warn** — declared
  R3/R4 never claimed in any mode); lifecycle `_notify`/`_flush_notify`
  to `/publish` (start=progress audit-only, finish=milestone,
  fail/stalled=alert; server noise policy debounces TG).
- `scripts/board/runner-agent.py` — single-file twin of the gate
  (`RUNNER_WAITING_GATE`), kill-switch + disk floor inside
  `_capacity_reason` (keeps /ready honest), `_notify` on claim/finish.
- `scripts/ada/kanban-act.py` — independent-review gate: `report:`-linked
  or `model_report:` cards can't auto-close on self-referential checks —
  `auto_done_when` must include `verified_true` or `git_merged`.

**SSOT / jobs / cards**
- `ssot.devin-autonomy.yml` waiting_cards: implementation, reporting,
  dry-run, readiness checklist (day1 done), pilot evidence recorded.
- `ssot.jobs.yml` + rendered `systemd/generated/idc03/chaba-unattended-report.{service,timer}` — daily 08:30 ICT on idc03.
- `ssot.kanban.yml` card_schema: `model_report` field + execution-gate note.
- `docs/ssot/jobs/kanban/2026-10-08-kanban-act-loop.yml` followup pointer added.
- Job runbook: `docs/ssot/jobs/kanban/2026-11-08-hands-off-waiting-cards.yml`.
- 5 pilot cards `docs/ssot/kanban/cards/unattended-pilot-*.yml` (backlog,
  read-only script cmds on idc03, R0/t2, artifact+verifier declared).

## Result / evidence

- `test_waiting_cards` 25/25 pass; `test_kanban_act` 18/18; related board
  suite (rails, claim-order, starvation, push-guard, close-out) 82 tests
  OK — warn mode verified live in test output (warns, still claims).
- Pilots: **5/5 ELIGIBLE** via `waiting_cards.py --evaluate`.
- Negative evidence: R3/R4 → never=True HOLD; open request → HOLD;
  missing host/artifact/verifier/recoverability → HOLD; R2 w/o backup
  proof → HOLD; `backup_fresh=True` → ELIGIBLE.
- `--board` live run: 1 queued card evaluated → HOLD (pre-contract fields,
  expected under warn mode).
- `unattended-report.py --dry-run` renders full digest correctly.
- `render-jobs.py --check` OK 98 jobs; `ssot-validate-all` 4/4 valid.

## Caveats / how to verify

- Gate defaults are **warn** everywhere — merging changes claim behavior
  only for declared R3/R4 (now never claimed) plus the new preflight
  freezes. Strict mode flips after the day-3 checklist (kill-switch drill
  + recoverability backfill on queued cards).
- runner-agent is a single-file deploy — the updated file must be copied
  to each runner host; until then remote runners keep old behavior.
- Pilots are backlog/not-queued by design: live end-to-end evidence is the
  day-2 checklist item after merge+deploy (queue one `unattended-pilot-*`).
- R2 cards need `WAITING_BACKUP_PROOF` or a `backup_fresh=True` env — no
  producer wired yet (followup in job doc).
- Verify: `python3 -m unittest tests.board.test_waiting_cards`,
  `python3 scripts/board/waiting_cards.py --board`,
  `python3 scripts/board/unattended-report.py --dry-run`.
