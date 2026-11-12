# Dispatch outcome — primer-v2-semantic-match (gate check)

Card: `primer-v2-semantic-match` (OPS-1277) on runner mn01.
Job doc: `docs/ssot/jobs/kanban/2026-11-09-primer-v2-gate-close.yml`.

## Result: gate-closed, not built

The card is `blocked_by` `primer-efficacy-measurement` with an explicit
gate in its spec: *read the verdict first; if compounding is
contradicted, this card should be closed not built.*

Read `reports/primer-efficacy-2026-11-09.md` (lives on branch
`dispatch/20261109-154659-goal-prove-or-kill-the-primer-`, not yet merged
to master at session time). Verdict: **CONTRADICTED — the mechanism is
not running**:

- 15 primer injections ever, all 2026-10-09 → 10-11; zero since.
- runner-agent lane = ~96% of dispatches (0/893 primed — no code path).
- `lp.build()` crashed on plain-string comms entries (fail-open hid it).
- Zero-injection never logged — dead primer was invisible.

That is the literal gate condition, so the card was closed via board-api
(`POST /action do=close` → "moved to done") with an explanatory comms
line. No code was written — semantic selection upgrades a stage that
isn't the bottleneck; nothing fires to select.

## What changed

- Board state only: comment + close on `primer-v2-semantic-match`.
- Trail: this outcome doc + job doc above. No repo code/config changes.

## Where the real work lives

- `_comms_candidates` string-comms crash — already fixed in
  `scripts/board/lesson_primer.py` (~line 202, merged).
- `runner-agent-primer-coverage` (doing) — wires the primer into the
  ~96% lane.
- `lesson-primer-scoring-fixes`, `positive-signal-primer` — done.
- Revisit semantic v2 only if the post-fix A/B (design in the efficacy
  report) returns a supported verdict on compounding.

## Verify

- `GET /card?id=primer-v2-semantic-match` → column=done,
  action.status=done, comms carry the gate rationale.
- Efficacy report: `git show
  origin/dispatch/20261109-154659-goal-prove-or-kill-the-primer-:reports/primer-efficacy-2026-11-09.md`.
