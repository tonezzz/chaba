# Dispatch outcome — standard-gate-visibility-everywhere (attempt 3)

## What was found

The card's deliverable **already landed in origin/master** — this
dispatch is a verification pass, not new work.

- Commit `136774f330` ("ssot(devin-autonomy): gate-visibility
  standard — every skip/defer/hold owes a consumer-visible reason")
  from attempt 2 (`dispatch/20261125-053219-...`) is an ancestor of
  origin/master; merge-sweep also merged it as `b72674cd` at
  2026-11-25 12:55 and auto-closed the card.
- `docs/ssot/infrastructure/ssot.devin-autonomy.yml` on origin/master
  contains the `gate_visibility:` block (line ~169): rule, scope
  (runner-agent, kanban-dispatch, kanban-act, Ada sweep tools, mddb
  workers + extension to service-level retry loops and non-card
  queues), the four-part contract (specific reason / normalized
  debounce / per-item vs fleet-level consumer-visible surface /
  awaiting_action only for deterministic fleet gaps), shipped
  exemplars, a nonconforming list, and a new-component checklist.
- `docs/ssot/jobs/kanban/2026-11-25-gate-visibility-standard.yml`
  exists on origin/master as the job record.

## Why this dispatch ran anyway

Tony's VERIFY-QUEUE triage at 14:03 held the card back to backlog
("dispatch attempt produced no committed deliverable ... No code
landed in origin/master") — a stale/false-negative read: the merge
had already happened at 12:55. The card was re-queued and
re-dispatched at 14:45 (attempt cap re-armed by Tony at 14:15).

## What this attempt changed

- Nothing in the repo beyond this outcome doc. No code, SSOT, or
  deploy changes — duplicating the standard would be churn.
- Verified content against the spec verbatim: the generalized
  standard, all five named components, the rate-limit +
  consumer-visible-surface contract, and the journal-is-not-a-
  surface clause are all present.

## How to verify

- `git merge-base --is-ancestor 136774f330 origin/master` → true
- `git show origin/master:docs/ssot/infrastructure/ssot.devin-autonomy.yml | grep -n gate_visibility` → line 169
- `git show origin/master:docs/ssot/jobs/kanban/2026-11-25-gate-visibility-standard.yml`
- Card comms on `standard-gate-visibility-everywhere` carry the
  attempt-2 done note + merge-sweep verified line.

lessons:
- VERIFY-QUEUE triage can fire on stale state — check
  `git merge-base --is-ancestor <commit> origin/master` and the
  card's own comms (merge-sweep "verified/auto-closed" line) before
  treating a "no deliverable" verdict as real; this card was
  re-dispatched ~2h after its content had already merged.
- A re-dispatch of an already-merged doc-only card should verify and
  close, not re-produce the artifact — the correct deliverable is
  evidence + this outcome doc.
- Dispatch-outcome docs must be committed on the dispatch branch or
  merge-sweep counts the attempt as "no commits" (attempt-1 failure
  mode); commit even when the substantive work already exists.
