# dispatch outcome — chaba-memory-producer-hygiene

Commit `e03f0bbe` on `dispatch/20261009-195508-three-producers-all-in-this-re` (not pushed).

## What changed

**1. Lifecycle events now tagged structurally**
- `scripts/chaba/recent-event.py` — new `--kind` flag; stored as `kind:` on the
  entry and re-applied on refresh-on-re-mention merges.
- `scripts/devin/session/devin-session-end.sh` — now appends
  `session ended (<reason>)` to recent-events.yml via recent-event.py with
  `--kind lifecycle` and `--ref devin-session:<id>`. Best-effort: a missing
  script or failure only logs to stderr.
  (The repo copy previously lacked the recent-event call entirely — the
  deployed hook under `~/.config/devin/scripts/` on tony-dell is a superset;
  this makes the repo copy emit the tagged form on next hook sync.)
- `scripts/chaba/render-memory.py` — recent-events source gains `drop_kind`
  (list); matching entries count into the existing "…(N routine events
  hidden)" rollup line. `docs/ssot/chaba/ssot.chaba.memory.yml` sets
  `drop_kind: [lifecycle]`; the `drop: ["^session ended"]` regex stays as
  defense-in-depth for legacy untagged rows.
- `scripts/chaba/render-report-feed.py` — `kind == "lifecycle"` entries fold
  into the lifecycle rollup alongside text-regex matches.

**2. Digest sample caps**
- `scripts/ada/spend-report.py` — ## spend emits at most 1 representative
  `xN <line>` sample per host (was 3 mid-sentence-truncated journal lines);
  header count + ⚠ unchanged.
- `scripts/ada/caddy-report.py` — ## apps emits at most 1 `slow` line per host
  (was 2); aggregated top/err counters unchanged. (personal-rollup.py itself
  needed no change — it just calls these block functions.)

**3. Empty pins skipped**
- `scripts/chaba/immediate-pin.py` — entries with no task/next/open are not
  written ("skipped: <session> — no task/next/open to pin"); a legacy stub for
  the same session id is removed on the skipped write. Auto-derived `pointer`
  alone does not count as resume info.

**4. Convention documented**
- `ssot.chaba.memory.yml` sessions section now states the session-memory.md
  entry convention: `## Compaction <id>` / `## Session end <id>` are entry
  headers; `## N. Section` blocks are fragments of the entry above —
  `entry_match` depends on it staying stable. immediate/recent-events
  descriptions updated to match producer behavior.
- Job doc: `docs/ssot/jobs/kanban/2026-10-09-chaba-memory-producer-hygiene.yml`.
- Card comms updated in `docs/ssot/kanban/cards/chaba-memory-producer-hygiene.yml`.

## Verification (all run with sandboxed HOME — no real state touched)

- `recent-event.py --kind lifecycle` → entry written with `kind: lifecycle`.
- `devin-session-end.sh` on `{"session_id":"stub-test-1","reason":"other"}` →
  recent-events.yml gains `session ended (other)` + `kind: lifecycle`;
  render-memory folds it to `…(N routine events hidden)`.
- Legacy untagged `session ended` rows still drop via the regex; normal
  events (staleness alert) render with ref.
- `spend_block`/`caddy_block` on fake rows → ≤1 sample line per bucket.
- `immediate-pin.py --session x` with nothing → skipped, no file/entry;
  with `--task` → pinned; re-pin of an empty session still skipped.
- `py_compile` on all touched py, `bash -n` on the hook, yaml.safe_load on all
  touched yml. Card expected-goal grep exits 0.
- `node scripts/ssot-validate-all.mjs` NOT run — node is not installed on
  idc02. Recommend running it on tony-dell before merge.
