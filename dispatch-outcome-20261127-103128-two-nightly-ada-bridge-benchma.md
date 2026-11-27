# Dispatch outcome — ada-ocb-eval + ada-ocb-smoke harness fix (idc02)

**Card:** `ada-ocb-eval-smoke-harness-fix` (ADA-1489)
**Repo touched:** `ada-voice` (the units run `~/CascadeProjects/ada-voice`
on idc02 — the card said repo=chaba but the harness lives in ada-voice;
chaba side only got the job-trail yml + this outcome doc).

## Diagnosis — two unrelated root causes, no gate-contract regression

1. **ada-ocb-eval 7/10 since 2026-11-27 00:20** — `tests/eval_ocb/
   cases.yml` still probed `ADA-0172` (ada-ocb-board-read-latency) and
   `ADA-0174` (ada-ocb-regression-suite). Both were archived out of
   board-api `/cards` between Nov-26 18:20 and Nov-27 00:20 (archive-done
   cap sweep, board >600). `find_card` fell through to token scoring →
   `ok=false` on all three card-tool cases. Same fixture-rot class as
   the smoke suite's ADA-0172→ADA-1110 repoint that morning — the eval
   cases were missed then.

2. **ada-ocb-smoke flake at 10:00** — `find_card ADA-1110` took 10.6s
   (idc03 board-api slow under load), then `ada_context_pack` dropped
   its card leg ("card snapshot missing from pack"). `_context_card` ran
   three sequential **uncached** `/cards` fetches — including an
   `/cards?id=<ref>` probe that can never match (id= matches card `id`,
   never `ref`) — inside the shared 8s pack deadline, ignoring the
   `_snapshot_cache` that `find_card`/`_pick_cards` had just warmed.

## Fix (ada-voice `912e064`, branch `dispatch/20261127-103128-two-nightly-ada-bridge-benchma`, pushed to origin)

- `tests/eval_ocb/cases.yml` — repoint the three cases to ADA-1110
  (the live fixture card the smoke suite already uses); expectations
  updated to its id/ref; header comment warns fixture refs must be
  live cards.
- `opencode/ada_mcp.py` — `_context_card` now resolves through
  `_compact_cards()`/`_fetch_card_full()` (shared snapshot cache) with
  deadline-bounded `timeout=` plumbed through `_get_json_cached` and
  both helpers; skips the guaranteed-miss `id=` probe for ref-shaped
  needles. Assertions untouched — provider robustness only.

## Verification (all on idc02, real units)

- `pytest tests -k 'opencode_ada_mcp or ocb or eval_ocb'` → **110 passed**
- `ada-ocb-eval.service` → **Result=success**, score **10/10**,
  wrote `ada-ha-scenario-reports/benchmark/ocb-eval-20261127-105551`
- `ada-ocb-smoke.service` → **Result=success**, all checks PASS,
  wrote `benchmark/ocb-smoke-20261127-105608` (+ ocb-bench rollup)
- context_pack card leg: ~8–9.5s → ~2.5s warm (cache hits)

idc02 checkout left on `main @912e064` (ahead of origin/main by the
dispatch commit) — merge-sweep lands the branch, then `git pull
--ff-only` fast-forwards cleanly.

## Notes for the board

- Comments posted to `timer-alert-idc02-ada-ocb-eval` and
  `timer-alert-idc02-ada-ocb-smoke` with the resolution.
- Fixture rot is recurring (3rd hit in 2 days): any suite probing a
  specific card ref breaks when archive-done retires it. ADA-1110 is
  done+recent (last in the cap sweep's oldest-first order) but will rot
  eventually — candidate follow-up: a permanent non-archivable fixture
  card or a liveness preflight in the suites.

lessons:
- [timer-alert-idc02-ada-ocb-eval] eval cases.yml fixture refs rot the same way smoke fixtures do — grep BOTH suites for card refs whenever archive-done runs; cases.yml was missed in the ADA-0172→ADA-1110 repoint.
- board-api `/cards?id=` matches card `id` only, never `ref` — probing it with a ref (ADA-1110) is a guaranteed miss that still costs a fetch inside a deadline budget.
- ada_mcp `_context_card` bypassed `_snapshot_cache` entirely — inside an 8s pack deadline, 3 uncached sequential fetches die on any board-api slow spell; route card resolution through the shared cached helpers.
- dispatch cards routed repo=chaba can still have their real harness in ada-voice — the units' ExecStart WorkingDirectory is the source of truth, not the card's repo field.
