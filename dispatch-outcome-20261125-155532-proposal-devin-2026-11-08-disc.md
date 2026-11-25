# Dispatch outcome — kanban-retention-archive-done-cards-olde-bba115

Card: `kanban-retention-archive-done-cards-olde-bba115` (KNB-1178)
Date: 2026-11-25 · branch `dispatch/20261125-155532-proposal-devin-2026-11-08-disc`

## Result: lane already shipped — verified end-to-end, two real gaps fixed

This card was re-queued by the overnight dispatcher, but the archive lane
has been live since 2026-11-08 (PRs #120/#121: board-api `do=archive` /
`do=unarchive`, `_archive_index`, `archive-done.py` sweep,
`chaba-kanban-archive.timer` daily 04:20 on idc03) and extended 2026-11-09
(commit `2049bf1d76`: `--cap 600` archives oldest done >7d verified-or-not).
Phase 3 (done-column paging, PR #125) and the standalone `archive.html` +
`archive.json` renderer outputs are also already in tree. Design deviates
from the spec's literal `column: archive` + lazy-fetch: archived cards
move to `docs/ssot/kanban/cards/archive/*.yml` (1176 files, in git,
off-board) — payload shrinks harder and lookups stay resolvable.

## What I changed (worktree diff, unmerged)

- `scripts/board/board-api.py`
  - `GET /cards?id=<slug>` now resolves archived cards: on an id-filter
    miss it falls back to `_archive_index()` (same contract `/card/<id>`
    already had — verified live that it returned `count:0` before) and
    re-runs `card_query` on the archived card with `id` removed, so
    column/action_status/since/fields/comms_tail filters still apply.
  - `do_archive` + new `_parse_updated` accept date-only `updated`
    (`%Y-%m-%d`) in addition to `%Y-%m-%d %H:%M` — auto-generated cards
    (runner-auto-*, disk-auto-*, cms-auto-*) stamp date-only and could
    never archive before.
- `scripts/board/archive-done.py` — same `_parse_updated` tolerance in
  `scan()` so the sweep lists what the door now accepts.
- `tests/board/test_board_api_reads.py` — new
  `test_cards_id_resolves_archived_card` (real loopback HTTP): archived
  hit by id and by ref, compact projection, remaining filters apply,
  live/unknown ids unchanged.
- `tests/board/test_archive.py` — date-only `updated` coverage for both
  `do_archive` and `SweepPlanTest.plan`.
- `docs/ssot/jobs/kanban/2026-11-25-archive-retention-verify-and-gaps.yml`
  — full trail: verified state, findings, decisions, verify steps.

## Verified

- `pytest tests/board/test_archive.py tests/board/test_board_api_reads.py`
  — 59 passed; `pytest tests/board/` — 1040 passed; `board-api.py
  --selftest` ok; `render-board2.py` writes cards.json (799 live) +
  archive.json (1176) + archive.html.
- Live board-api: `/health` ok; `/card/ada-acl-explain` (archived) 200;
  `/cards?limit=1` total=799 == local render count.
- `archive-done.py` dry-run today: 0 verified + 0 cap candidates.

## Findings (reported on card; no action taken — transient + self-healing)

- **Starvation window:** every parseable done card (640/646) has
  `updated` <24h because this morning's stale-runner-agent defer notes
  ("installed runner-agent drifted", 07:43–07:51) landed on done cards —
  each comm bumps `updated`, resetting the 7d clock. Drift converged
  ~15:42 (all fleet hosts byte-match the pin per the 15:47 dispatch
  outcome) and current runner-agent code skips off-queue columns for
  defer notes, so candidates should re-appear as stamps age past 7d.
  Same failure mode as the 2026-11-21 bulk `updated` rewrite — the
  `--days`/`min_days` recovery pass exists if Tony wants a catch-up sweep.
- 6–11 done auto-cards carry date-only `updated` (now archivable after
  this change deploys).

## How to verify after merge

- `GET /cards?id=<any-file-in-cards/archive/>` returns the card envelope;
  `&column=review` returns `total:0`.
- `python3 scripts/board/archive-done.py` lists date-only auto-cards once
  they pass the age gate.
- Daily `chaba-kanban-archive.timer` continues unchanged.

lessons:
- defer-note comms bump `updated` — automated noise on done cards resets
  the archive age clock; off-queue cards must never get producer comms
- auto-card producers stamp `updated` date-only — age-gated sweeps must
  parse '%Y-%m-%d' as well as '%Y-%m-%d %H:%M'
- card re-queues can be stale action flags — verify shipped state before
  re-implementing; this lane was live since 2026-11-08
