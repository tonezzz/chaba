# dispatch outcome — ada-card-loop-tiers (participation tiers for Ada)

## What the dispatch asked

Define Ada's participation tiers on the kanban loop (T0 observe → T4 act),
the educate-vs-educated standard, the card-judgment bench domain that gates
T3, and the mutual reach-out escalation ladder. Expected goals: an
`ssot.ada-participation.yml` file and `card-judgment` present in the bench
registry.

## What changed

- `docs/ssot/infrastructure/ssot.ada-participation.yml` — the tier ladder.
  T0/T1/T2 marked **live** (mechanisms all exist: GET /cards, POST /comment
  as `from:ada`, POST /request + board_notify push + request-sweep re-ping).
  T3 queue **gated** on the card-judgment bench; T4 act future/micro-entity.
  Also: educate_standard (fresher VERIFIED state educates; correction
  without a check is an opinion), the mutual 5-rung escalation ladder
  (board_request → ha_notification → openclaw → telegram → ntfy), hard
  boundaries synced with `docs/design/ada-kanban-access.md`.
- `docs/ssot/infrastructure/ssot.nest-bench.yml` — new bench-domain
  registry. Adds `card-judgment` domain: corpus = historical done-cards
  with proven-right outcomes; metrics = correction-precision,
  correction-recall, appropriate-deference, action-accuracy. Declared T3
  unlock: ≥0.85 accuracy / ≥0.90 deference / ≥0.80 precision on ≥50 cases,
  held 3 consecutive runs. Shadow mode before unlock.
- `docs/ssot/jobs/kanban/2026-10-07-ada-card-loop-tiers.yml` — trail.

## Finding (recorded, not fixed)

`ada_board_write` (ada-pi) wraps comment/respond/read/create but not
`/request` — Ada can answer board requests but cannot raise them through
the tool. Endpoint accepts `from:ada` already; one-action patch needed.

## Verify

- `test -f docs/ssot/infrastructure/ssot.ada-participation.yml` ✅
- `grep -q card-judgment docs/ssot/infrastructure/ssot.nest-bench*.yml` ✅
- `node scripts/ssot-validate-all.mjs` → 1617/1617 valid ✅
- Commit `5b3d1946` on `dispatch/20261007-175058-participation-tiers-for-ada-on`
