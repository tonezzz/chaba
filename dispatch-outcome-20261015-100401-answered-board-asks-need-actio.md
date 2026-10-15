# Dispatch outcome — knb-answer-action-triage

## Task
Answered board asks need action-triage — `/respond` recorded answers but
nothing executed them; 163 answered-but-unexecuted requests sat on the
live board (~16 on live cards, rest on done cards). Card's open request
`answer-triage-policy` offered auto-verb (★ suggested) / manual /
per-option — dispatched with the suggested default.

## What changed (branch dispatch/20261015-100401-answered-board-asks-need-actio, commit b637eefa1)

- **`scripts/board/answer-sweep.py` (new)** — the triage half of the
  request lifecycle, riding kanban-sync (15min) after request-sweep.
  For each answered, unexecuted, unowned request (plus card-level ask)
  on non-done/lab cards it resolves the answer to a board action:
  1. dict-option `action: queue|retry|close|hold|none` field (new
     per-option schema — emitters declare consequences at request time)
  2. else dict-option id / first word of the answer head -> VERBS:
     queue·dispatch·proceed·go·run·start·build·yes·approve·continue →
     queue; retry → retry; close·done·resolve·retire·archive → close
     (merge-guarded — erred guard *defers*, stricter than the board
     button); hold·park·defer·wait·later·keep·stay·backlog → backlog;
     superseded·duplicate·self-resolved·merged·n/a… → receipt-only
     `executed: <date> none` stamp.
  Guards: soft assent (yes/approve) doesn't fire as unmatched free text
  on an options ask; verbs defer on starting/running actions (a 'close'
  lands once the session finishes); 'queued' cards can still be
  disarmed by hold/close; non-dispatch action types (manual/container)
  defer queue; conflicting verbs defer the card; one verb per card per
  pass; ANSWER_SWEEP_MAX=10 cap; deferred notes dedup vs last-8 comms.
  Executed answers stamp `executed:`; `awaiting_action` clears when
  nothing remains to triage and is **healed** onto live cards whose
  pre-flag answers are still unexecuted (the visibility gap).
- **`scripts/ada/kanban-sync.sh`** — runs answer-sweep.py after
  request-sweep.py; existing `git add docs/ssot/kanban/cards/` persists.
- **`docs/ssot/kanban/ssot.kanban.yml`** — requests[] schema gains
  `executed:` and option `action:`; /respond doc records the sweep.
- **`docs/ssot/infrastructure/ssot.jobs.yml`** — kanban-sync note lists it.
- **`docs/ssot/jobs/kanban/2026-10-15-answer-sweep.yml`** — job trail.
- **`tests/board/test_answer_sweep.py`** — 22 unittest cases.

## Verification
- `python3 -m unittest tests.board.test_answer_sweep` — 22/22 pass;
  full `tests/board` suite 131 pass, 2 skipped (pre-existing).
- Dry-run + real pass over a 737-card live snapshot (board-api /cards):
  10 executions — real queue/hold flips (e.g. `queue for dispatch ★`
  answers now arm dispatch; `keep open`/`stay free` hold),
  "(already running)" stamps on in-flight cards, `none` receipts for
  superseded answers, stale flags cleared on done cards. Decision
  answers (two-pools, move-cache, spend/hardware picks) correctly stay
  unmapped+flagged. Second pass fully idempotent.
- Live takeover: first kanban-sync tick after the branch merges.

## Left for Tony
- Request `answer-triage-policy` stays open (his call) — auto-verb is
  implemented; `action:` per-option is available to emitters; choosing
  manual = simply not adopting verbs.
- Unmapped decision answers remain awaiting_action in needs-you —
  that's the honest triage list now.

## lessons:
- The board already had the executor precedent: lab-review-sweep's
  answered→execute→`executed:`-stamp pattern; generalizing it beats a
  new mechanism.
- dict-option answers land as `id — label` text — the option id is the
  reliable verb carrier, the label is free prose.
- 'queued' is not busy: answers must be able to disarm a queued card;
  only starting/running defer verb execution.
- Merge-guard asymmetry: human button tolerates guard errors, an
  autonomous sweep must defer on them.
