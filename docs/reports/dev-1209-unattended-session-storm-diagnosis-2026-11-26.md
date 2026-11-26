# DEV-1209 — Repeated unattended Devin sessions: diagnosis and re-enable conditions

Date: 2026-11-26 (evidence window 2026-11-08)
Card: `diagnose-unattended-devin-session-storm-20261108` (DEV-1209)
Status: root cause identified, fix deployed and canary-verified; runner source stays paused pending Tony's resume approval.

## Verdict

The storm was **not** a new trigger. The repeated `You are running unattended via devin-dispatch …` sessions were legitimate dispatch sessions being **re-spawned in a loop** because board-api `/action` acknowledged claim/move/finish writes without persisting them (KNB-1196). Containment (all runner-agent / kanban-dispatch timers stopped+disabled) remains correct until the re-enable checklist below is met and Tony approves.

## Source of the unattended sessions

- `scripts/devin/devin-dispatch.sh` writes the prompt header `You are running unattended via devin-dispatch (a headless, user-triggered session)…` into every dispatched task's `prompt.txt` (lines ~350). This is the standard prompt prefix for every dispatch-claimed card — it is expected, not an anomaly.
- `scripts/devin/session-prune.py` treats that exact prefix as the marker of dispatch sessions.
- Each session ran inside a `devin-task-*` systemd unit spawned by `kanban-dispatch.timer` → claimed and executed by `runner-agent` on the host. Devin Desktop ACP processes on Omen/Dell were correctly left alone — they don't carry the marker.

## Status-transition failure chain (KNB-1196)

1. `kanban-dispatch` queued a card; `runner-agent` claimed it → `POST /action do=claim` → HTTP 200.
2. In `board-api.py`'s `/action` handler, `do_claim` / `do_move` / `do_finish` mutated the in-memory card under the flock but the handler **returned without `save(p, card)`** — disk stayed `action.status=queued`.
3. Runner finished the task → `do=finish` hit `raise ValueError(f"not running (status=queued)")` (board-api.py:1908) → finish failed, repeatedly logged on Omen.
4. The card still read `queued` on disk → the next dispatch tick re-claimed it → a **new** `devin-task-*` unit and a new unattended session. Same window produced the confirmed duplicate: `timer-alert-idc03-chaba-jobs` got two dispatches 28s apart on tony-macbook and idc02 (KNB-1196 card note), and a `do=close` that returned ok was absent from the card afterwards (stale-load clobber).

## Fix status

- **Merged:** `91f327ca` (PR #128, 2026-11-08) — `/action` now saves the card for claim/move/finish (`card["updated"] = now(); save(p, card)`), making each transition durable under the flock.
- **Concurrency test:** `tests/board/test_board_api_action_persistence.py` — two concurrent claims now yield exactly one 200 and one 400; move/finish persistence covered. Re-run 2026-11-26 on this checkout under Python 3.12: **7/7 pass** (note: suite needs ≥3.11 — `publication.py` uses multi-line f-strings; local 3.10 cannot import it).
- **Live canary:** `knb1196-live-canary-20261108` (OPS-1219) — claim→finish→move persisted end-to-end on the deployed API; card archived done+verified.

## Current containment (verified from card comms, unchanged by this report)

| Host | runner-agent.timer | Active devin-task units |
|---|---|---|
| tony-omen | stopped + disabled | none |
| tony-macbook | stopped + disabled | none |
| idc02 | stopped + disabled | none |
| idc03 (kanban-dispatch + runner-agent) | stopped + disabled | none |
| mn01 | disabled | none reported |
| tony-dell | no runner timer | none |

Live host state was last verified by the 2026-11-08 sweep in the card comms; this session has no tailnet access, so per-host unit state should be re-confirmed at resume time (cheap: `systemctl --user is-enabled runner-agent.timer`).

## Safe re-enable conditions

Root cause is fixed, but two gates remain before any timer is re-armed:

1. **Converge installed runner-agent to the pin.** Every fleet host still emits daily `defers: installed runner-agent drifted from repo …runner-agent.py` (latest 2026-11-26 03:58 on this card). The canonical path is `tony-dell runner-agent-converge.timer → ansible deploy-runner-agent.yml`, gated by the sha256 pins in `scripts/devin/runner-tooling.manifest.json` (`runner_agent` pin `1514c75c…`). Do not re-enable a host's timer until `runner-fleet-health.py` reports its installed copy matches the pin — a re-armed drifted runner is the known re-break path (idc02 ada-ocb converge incident, ADA-1340).
2. **Tony's explicit resume approval.** He already answered `resume-paused-runners-knb1196`: *"Keep all paused until a separate resumption approval."* Recommended resume order (unchanged): monitored idc03-only canary (kanban-dispatch + runner-agent) → watch one claim→finish→move cycle persist → then re-enable Omen/MacBook/idc02/mn01, one host at a time.

Kill switch for an instant freeze if needed: `touch /tmp/no-kanban-dispatch` on the dispatch host (`ssot.devin-autonomy.yml` `kill_switch`).

## Artifacts preserved

No session/task data was deleted: runner journals, `devin-task-*` units' task dirs, and the dispatch task store were left in place per the card's guardrail.
