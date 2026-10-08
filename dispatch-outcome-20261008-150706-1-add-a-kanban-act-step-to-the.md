# dispatch-outcome — kanban-act-loop

Card: `kanban-act-loop` — wire kanban-act into the timer loop + make the
auto_done_when close-out contract a card standard.

## What changed

**(1) kanban-act wired into the timer loop (manifest-level fix).**
The real gap: `ssot.jobs.yml` is the authoritative manifest and renders one
`ExecStart` per job — the rendered `chaba-kanban-brief.service` only ran
`kanban-brief.py`, silently dropping `kanban-act.py` and `nest-overview.py`
which the hand-maintained `systemd/` unit carried.

- `scripts/render-jobs.py` — `exec:` now accepts a string or a list; a list
  renders one `ExecStart` per entry (oneshot chain semantics).
- `scripts/job-dispatcher.py` — list `exec` joins with `&&` (same convention
  for dispatcher jobs).
- `docs/ssot/infrastructure/ssot.jobs.yml` — `chaba-kanban-brief` declares
  all three steps (brief → act → nest-overview) plus the `env`/`cwd` the
  rendered unit was missing (`KANBAN_BRIEF_LLM_*`, WorkingDirectory);
  timeout 2m→5m; `exec` list documented in conventions.
- `systemd/generated/tony_dell/chaba-kanban-brief.service` — re-rendered,
  now carries all three ExecStarts.
- `systemd/chaba-kanban-brief.service` (legacy) — TimeoutStartSec 120→300
  for parity.

**(2) Card standard.** `docs/ssot/kanban/ssot.kanban.yml` `card_schema` now
documents `autonomy` / `auto_done_when` / `done_note` / `verified` /
`auto_close`, states that new dispatch/lab cards SHOULD declare the
contract, and adds `kanban-act` to the ops lanes. New starter template:
`docs/ssot/templates/card.yml`.

**(3) New check kinds in `scripts/ada/kanban-act.py`.**
- `git_merged:<branch-prefix>` — every `origin/<prefix>*` head is an
  ancestor of `origin/master|main` (local remote refs; ref-name whitelist
  guards injection).
- `verified_true[:<id>]` — reads `action.verified` (merge-sweep/close_out
  stamp) or top-level `verified`; no arg = the card itself. This is the
  dispatch-card idiom: merge-sweep sets verified, kanban-act turns it into
  `column: done`.

**(4) Safety gates added** (were missing, spec required): only
`column: review` cards are evaluated; `review_kind: decide` always holds;
open `requests[]` or an unanswered `ask` block the close. MAX_ACTS cap and
the per-close `kanban_act` ops event are unchanged.

**(5) CI nudge.** `scripts/ssot-validate-all.mjs` warns (never errors) on
review-column cards with neither `auto_done_when` nor `review_kind` — fires
today on `lab-cf-kv-claw-channel` and `nest-bank-router`.

## Verification

- `python3 -m unittest tests.board.test_kanban_act` — 18/18 pass (new file;
  covers gates, verified_true variants, git_merged against a real
  bare-origin fixture incl. injection rejection).
- `python3 scripts/render-jobs.py --check` — OK, 42 jobs; re-render wrote
  the 3-ExecStart unit.
- `python3 scripts/ada/kanban-act.py --dry-run` — clean; synthetic review
  card verified would-act → hold-on-decide → hold-on-open-request →
  released-when-answered.
- `node scripts/ssot-validate-all.mjs <touched files>` — all valid; warning
  fires only where intended.

## Trail

`docs/ssot/jobs/kanban/2026-10-08-kanban-act-loop.yml` — full design record.

## Note for the operator

The rendered unit reaches tony-dell on the next `render-jobs.py --install`
(or manual unit sync). The installed unit already ran kanban-act if it is
the hand-maintained copy, so behavior is continuous either way; after
install, kanban-act starts draining t2 review cards on the `:0/30` tick.
