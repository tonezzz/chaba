# Dispatch outcome — report-loop-comment-delivery (2026-10-07)

Card: report-loop-comment-delivery — implement report-session-loop §3a
contract: card comms as a live input channel to running sessions.

## What changed

- `scripts/board/board-api.py`
  - `deliver_answer()` refactored into shared `_deliver_to_session(card,
    record)` — same local-write / ssh-runner machinery, same never-raises
    contract returning a comms note or `""`. `at`/`card` stamped inside;
    `kind` names the line in notes.
  - `/respond` still delivers `{at, card, from, request_id, answer}` —
    now with `kind:"answer"` (via thin `deliver_answer` wrapper).
  - `/comment` path: after `comms_add`, `deliver_comment()` delivers
    `{at, card, from, kind:"comment", text}` when
    `action.status=='running'` AND `from ∈ {ada, tony}`
    (`COMMENT_DELIVER_FROM`). devin/chaba comments are never pushed —
    sessions don't get their own progress posts echoed back, chaba notes
    are noise. Delivery note lands in comms + response message, same as
    the /respond path.
  - Docstring endpoint list updated; `_selftest` extended.
- `scripts/board/kanban-dispatch.py` — `TASK_RAILS` gained the
  kind:"comment" contract line (comms = review input to weigh;
  request_id/answer lines stay authoritative).
- `scripts/board/runner-agent.py`, `scripts/devin/devin-dispatch.sh` —
  same answers.jsonl contract text updated for parity (start + resume
  prompts, remote-runner rails).
- `docs/ssot/kanban/ssot.kanban.yml` — /respond + /comment endpoint docs
  and `task_rails` description record both line kinds and the echo rule.
- `docs/ssot/jobs/kanban/2026-10-07-report-loop-comment-delivery.yml` —
  job trail.

## Verify

- `python3 scripts/board/board-api.py --selftest` → `selftest ok`
  (kind:"answer" on /respond lines; tony/ada /comment lines append
  kind:"comment"; devin/chaba comments append nothing; non-running card
  delivers nothing; bad ids/runner degrade to notes, never raise).
- `node scripts/ssot-validate-all.mjs` → 0 errors, 1 warning
  (ssot.kanban.yml bloat 391/350 — doc growth, pre-existing trend).
- `bash -n scripts/devin/devin-dispatch.sh` → clean.
- Live check: after merge + `board-api.service` restart on
  chaba-tony-dell, a tony/ada `/comment` on a running card should land
  as a `kind:"comment"` line in that session's `$TASK_DIR/answers.jsonl`
  (observable from the next dispatched session's task dir).

## Not done / needs approval

- Deploy is merge-to-master + service restart on the served checkout —
  left for review per the no-deploy rail.
