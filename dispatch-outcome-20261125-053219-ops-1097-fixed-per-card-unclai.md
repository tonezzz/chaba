# Dispatch outcome — standard-gate-visibility-everywhere (attempt 2)

## What changed

- `docs/ssot/infrastructure/ssot.devin-autonomy.yml` — new top-level
  `gate_visibility:` block codifying the standard: ANY component that
  decides not to act on a queued item (skip/defer/hold/retry-without-
  progress/park) MUST emit a rate-limited, consumer-visible reason on
  the item or a fleet-level surface. Includes scope (runner-agent,
  kanban-dispatch, kanban-act, Ada sweeps, mddb workers, plus
  service-level retry loops and non-card queues), the four-part contract
  (specific reason / normalized-reason debounce / per-item vs fleet-level
  surface / awaiting_action only for deterministic fleet gaps),
  exemplars from the shipped lanes, a nonconforming list, and a
  new-component checklist. `related:` now cross-references
  `docs/kb/devin-error-handling-standard.md`.
- `docs/ssot/jobs/kanban/2026-11-25-gate-visibility-standard.yml` —
  job record with context, decisions, and verify steps.
- Commit `136774f330` on branch
  `dispatch/20261125-053219-ops-1097-fixed-per-card-unclai` — this is
  the fix for attempt 1, which produced a dirty worktree and no commits
  (merge-sweep counted it failed).

## Result

Doc-only standard; no lane code touched. The standard names the
already-shipped exemplars (`note_defer`/`_defer_norm`, `_defer_note`,
`_flag_unclaimable`/`UNCLAIM_MARK`, `verdict_pass -> /ready`) so future
reviewers can flag deviations. SSOT takes effect on next served-checkout
pull; no deploy needed.

## How to verify

- `git show 136774f330 --stat` — two files, ~148 insertions.
- `python3 -c "import yaml; yaml.safe_load(open('docs/ssot/infrastructure/ssot.devin-autonomy.yml'))"`
- Read `gate_visibility:` at the end of the file; pre-commit SSOT
  validation passed during commit.

lessons:
- Attempt 1 failed merge-sweep with "session produced no commits" — a
  doc-only dispatch still MUST `git add` + `git commit` the deliverable
  in the worktree; writing files is not enough.
- ssot.devin-autonomy.yml already existed under docs/ssot/infrastructure/
  (not docs/ssot/ root) — the spec's "or the dispatch runbook" resolved
  to this file.
- Card comms are flooded by per-host "defers: runner-agent drifted"
  notes (debounce only fires per distinct reason); they are noise, not
  signal, when triaging a card's real state.
