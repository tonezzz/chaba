# Outcome — answers reach running sessions (board-answer-live-session)

## What changed (branch dispatch/20261006-101315-answers-reach-running-sessions, f43a9d0e)

- `scripts/board/board-api.py` — new `deliver_answer()`: after `/respond`
  saves an answer on a card whose `action.status=='running'`, it appends a
  JSON line `{at, card, from, request_id, answer}` to
  `$DISPATCH_DIR/tasks/<task_id>/answers.jsonl` on the runner host — direct
  write for local runners, `ssh <runner> 'test -d <dir> && cat >> …'` for
  remote ones (REMOTE_DISPATCH_HOSTS fallback). task_id/runner are
  regex-validated; `test -d` keeps fallback hosts from growing phantom task
  dirs. Best-effort — always returns a comms note, never raises.
- `scripts/board/kanban-dispatch.py` — TASK_RAILS: sessions told to poll
  `$TASK_DIR/answers.jsonl` before finishing (newest line wins per
  request_id).
- `scripts/board/runner-agent.py` — same rail for remote-runner sessions.
- `scripts/devin/devin-dispatch.sh` — start + resume prompts document the
  answers.jsonl channel next to needs-input.txt.
- `docs/ssot/kanban/ssot.kanban.yml` — /respond + task_rails contract updated.
- `docs/ssot/jobs/kanban/2026-10-06-answers-reach-running-sessions.yml` —
  trail doc.

## Verification

- `python3 scripts/board/board-api.py --selftest` → `selftest ok`.
- Live e2e on tony-omen: ran patched board-api on :18787 against a temp
  card {status: running, task_id: this session's task id}; POST /respond
  returned `answer saved — answer delivered to running session
  20261006-101315-…` and the line appeared in
  `~/.local/share/devin-dispatch/tasks/20261006-101315-answers-reach-running-sessions/answers.jsonl`.
  Temp card deleted, test instance stopped.
- Prior attempt (10-05) had already proven the same path; this run
  cherry-picked it, added the card field + no-phantom-dir guard, and
  covered the surfaces it missed (runner-agent rails, dispatch prompts,
  SSOT doc).

## Notes

- Lands with the next board-api deploy (served checkout chaba-tony-dell).
- `~/.local/bin/devin-dispatch` on tony-omen is older than the repo copy —
  refresh needed for new dispatches to carry the updated prompt.
