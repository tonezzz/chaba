# Dispatch outcome — memory-extract-merge-proposals (session 2)

Second session on this card; session 1 (dispatch 213852) built the
script, tests, ssot.jobs entry and published the first report — merged
to master (8e7b3cd9c4, e7e8b7de84). This session closed the remaining
DONE-WHEN items except the human review, which is parked on a board
request with a marked recommendation.

## What changed / happened

- **Timer installed on idc03** — `render-jobs.py --host idc03 --ids
  ada-memory-merge-proposals --install`; `systemctl --user list-timers`
  shows next fire **Sun 2026-11-22 10:30 +07**, after
  `ada-memory-distill` (Sun 09:45). DONE WHEN #1 met.
- **Hardening commit 1c605c48c9** — `scripts/ada/memory-merge-proposals.py`:
  - per-collection `search_errors` counted when `/vector-search` fails;
    surfaced in the report block, run metric, card comment and each
    `runs[]` state row — an embed-capped run reads "lower bound", not a
    false "0 candidates" (this exact outage was live during the session).
  - report window label uses the real `--draft-days` (was hardcoded 14d).
  - footer-only/empty drafts skip the embed call.
- **Job doc updated** (`docs/ssot/jobs/ada/2026-11-18-memory-merge-proposals.yml`).
- **Backlog catch-up run on idc03** — ran the updated script (staged at
  `/tmp/mmp` on idc03, repo layout preserved) with `--bank general
  --draft-days 60` once the paid embed cap reset at 23:00+07. Result:
  **3 real proposals** recorded into idc03 state
  (`~/.cache/ada-memory-merge-proposals.json`), 0 search errors,
  report re-published to `ada-cms-pages/memory-merge-proposals`
  (now lists the proposals with verbatim fact deltas), card comment
  posted. `merge-a6b85c92`, `merge-e4a2cf4e`, `merge-7b23a500` — all
  ada-ha-bank-general, heuristic-suggested `supersede`, but on inspection
  all three are restatements (one is a Thai translation of the
  canonical) → `reject` is the honest resolution for each.
- **Board request raised** — DONE-gate question with clickable options,
  recommended ★ `reject merge-a6b85c92`. Resolve command:
  `python3 scripts/ada/memory-merge-proposals.py --resolve <id>
  --action reject` on idc03.
- **New card filed**: `ada-session-summary-inflow-stalled` (ADA-0209) —
  root cause of the empty 14d window: `ada-memory-distill` runs fine
  (Sun 09:45, exit 0) but every `ada-ha-recall-summary-*` collection
  stopped receiving session summaries early Oct (tony newest
  2026-10-03, dev 2026-10-09, kk 2026-10-13, ada-dev empty). No
  source=extract drafts since ~2026-10-17; ~480 stale drafts sit
  unreviewed across banks.

## Verification

- `tests/ada_memory/test_memory_scripts.py` — 34/34 pass.
- `render-jobs.py --check` — OK 113 jobs, 8 hosts.
- `systemctl --user list-timers` on idc03 shows
  `ada-memory-merge-proposals.timer` → Sun 2026-11-22 10:30.
- Report live at `ada-cms-pages/memory-merge-proposals` — managed
  block shows the 3 proposals, correct `60d` label, resolve
  instructions.
- Embed outage during session: `all same-space providers down (OR
  daily-cap 5000 + Gemini failed + paid hourly-cap 150)`; recovered
  23:02 +07 when the paid hourly window reset.

## Status vs DONE WHEN

- [x] Timer runs weekly on idc03 — installed, next fire Sun 10:30.
- [x] First report published — `ada-cms-pages/memory-merge-proposals`,
  now with 3 real proposals.
- [ ] One real proposal reviewed end-to-end — human decision pending;
  board request `done-gate-pick-one-real-merge-proposal-a-807b17`
  raised with recommended option. State on idc03 is populated so a
  `--resolve` there works immediately.

## How to verify / finish

```
ssh idc03
python3 scripts/ada/memory-merge-proposals.py --list-pending
python3 scripts/ada/memory-merge-proposals.py --resolve merge-a6b85c92 --action reject
# draft gains meta merge_review=rejected; next run won't re-propose it
```
