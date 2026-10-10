# dispatch-outcome — runner-agent claim loop sort (card dispatch-priority-order)

## What changed

Priority was display-only: runners claimed queued cards in whatever
order `/cards` or the card-dir glob returned. Both claim paths now
drain in one shared order, implemented once in `dispatch_repos.py` —
the module kanban-dispatch already imports and runner-agent already
resolves per-host via `dr_module()` (no new file to deploy):

- `dispatch_repos.claim_sort_key(card, starve_hours, now_ts)` returns
  `(starved? 0:1, priority rank, updated-ts)`; `sort_claimable()`
  applies it as a stable sort.
- Rank map: `high 0 > medium 1 > absent/unknown 2 > low 3` — the same
  map `render-board.py` uses for the board's next-up column order, so
  what Tony sees as "next" is what claims next. (The card spec's
  "low > absent" phrasing was overridden by its own acceptance line —
  `normal` drains before `low` — and by the established display rank.)
- Starvation guard: a card whose `updated` is >= 12h old claims ahead
  of every fresh card — priority is a bias, not a ban. Tunable via
  `KANBAN_STARVE_HOURS` (kanban-dispatch) / `RUNNER_STARVE_HOURS`
  (runner-agent); 0 disables. A card with no readable `updated` can't
  prove its age, so it never takes the starvation tier — it only wins
  its own rank's oldest-first tie-break.
- `kanban-dispatch.py` phase A preloads cards and visits
  queued/starting ones in claim order; running/other cards keep
  filename order. All eligibility gates (autonomy tier, budget, retry
  cap, host pin, blocked_by, type, labels, runner, host cap) are
  unchanged — order never overrides eligibility.
- `runner-agent.py` `claim_pass` drains `_claim_order(cards)`; when
  `dispatch_repos` can't be resolved on the host it falls back to API
  order with a once-per-process journal warning (fleet-health already
  flags that drift as a violation).

Docs: `ssot.kanban.yml` `concurrency.claim_order`;
`ssot.operating-model.yml` priority section updated (was "closes the
current gap"); runbook `docs/ssot/jobs/kanban/2026-10-10-priority-
claim-order.yml`.

## Result

Commit `b031c146` on `dispatch/20261010-093409-1-runner-agent-claim-loop-sort`
(7 files, +392/−7). Not pushed — merge rides the normal close-out path.

## How to verify

- `python3 tests/board/test_claim_order.py` — 11/11 pass, covering the
  acceptance exactly: `[low old, high new, normal oldest]` drains
  `high -> normal -> low`; a 13h-old low beats a fresh high; starved
  high still beats starved low; eligibility gating intact
  (claimable()/blocked_by/gpu preflight run unchanged inside
  claim_pass).
- `python3 -m unittest discover -s tests/board` — 90 tests OK
  (1 pre-existing skip), no regressions.
- `python3 -m py_compile` clean on all three touched scripts.
- Fleet rollout note (in the runbook's gotchas): remote hosts need BOTH
  the redeployed `~/.local/bin/runner-agent` AND a pulled
  `~/CascadeProjects/chaba` before the order applies there; a stale
  checkout degrades to API order, never a crash.

## lessons:

- when a spec's literal text contradicts its own acceptance criteria,
  the acceptance is the contract — here "low > absent" lost to
  "normal drains before low", which also matches render-board.py's
  established rank map
- runner-agent is a single-file deploy: shared logic belongs in
  dispatch_repos.py (resolvable on every fleet host via dr_module),
  and every new import dependency needs a degrade-not-crash fallback
- card `updated` is free-text ("YYYY-MM-DD[ HH:MM]", +07) — parse it
  defensively and decide explicitly what unparseable means (here:
  oldest-in-rank, never starvation-tier)
