# dispatch outcome — report-bounded-surfaces

Card: `report-bounded-surfaces` (runner idc03). Machinery + one working
example of the bounded_surfaces standard — all five spec items done, no
L0 budgets added.

## What changed

- **`scripts/lib/bounded.py` (new)** — extracted from
  `scripts/chaba/render-memory.py`: `apply_budget`,
  `dedupe_consecutive` (×N), `drop_patterns` (+dropped count),
  `filter_status` (skip_status), `cap_entry` (entry_max_chars),
  `keep_last` (max_entries), plus `enforce_surface` — the whole-surface
  budget helper for multi-section rendered docs (ordered shed with
  in-place markers + hard cut).
- **`scripts/chaba/render-memory.py`** — imports the helpers; all
  inline copies removed. Render verified byte-identical (modulo
  timestamp) and an 11-case synthetic equivalence harness over
  rolling-log / recent-events / skip_status / budget paths: ALL EQUAL.
- **`scripts/report-system.py`** — renders as named section blocks
  (`overview, host-loads, domains, producers, recent-timeline,
  raw-data`) through the node's registry knobs: `suppress`, `dedupe`,
  `finding_max_chars`, `empty` (marker|hide; reports default to
  `_(empty — ran clean)_`), `limits` + `overflow_order`. Shed sections
  keep their heading + `_(shed — surface over soft budget)_` marker.
  `write_meta` now records `extra.chars` (+ `shed`, `over_hard`,
  `suppressed` when present).
- **`docs/ssot/infrastructure/ssot.reports.yml`** — `limits {soft:
  25000, hard: 50000}` + `overflow_order` on the `system-report` node
  only; current_state/next_steps updated.
- **`scripts/report/report-watch.py`** — new informational `overrun`
  class: `meta.extra.chars > limits.hard` → low-priority focus-inbox
  note (slug-deduped), never a page. Checked for every node with meta,
  independent of status.
- **`docs/ssot/jobs/infrastructure/2026-10-09-bounded-surfaces.yml`** —
  trail doc.

## Verify

- Memory render unchanged: run `render-memory.py` before/after — diff
  is timestamps only (done here; synthetic harness in this session also
  covered dedupe/drop/cap paths this host lacks data for).
- Shed: `report-system.py --registry <copy with limits.soft: 5000>`
  sheds sections in `overflow_order` with in-place markers; stops once
  under soft; `hard` truncates globally.
- Empty: `_(empty — ran clean)_` for contentless sections; `empty:
  hide` removes them.
- Overrun: sandboxed report-watch run flagged a fake over-budget node
  once (priority low), skipped in-budget/chars-less nodes, deduped.

## Notes

- One hardening fix inside `dedupe_consecutive`: blank separators can
  never be merge sources *or* targets (a heading-only entry's empty
  body would otherwise collapse into a preceding blank). No behavior
  change for memory renders.
- Rolling the fields onto other rendered nodes = per-node follow-ups,
  deliberately out of scope per the card.
- No commits/pushes/deploys — worktree only, per dispatch rules.
