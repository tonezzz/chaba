# dispatch outcome — prune-old-docs: log expired count separately from deleted

## What changed
- `scripts/ada/prune-old-docs.py` `sweep()`: added an `expired_seen`
  counter incremented per page by `len(expired)` — i.e. docs matching the
  stale predicate during enumeration, independent of delete attempts.
  Summary line now reads `collection: expired E, deleted D/S (>Nd on ts
  @host) in Ts` (dry-run: `expired E, would delete D/S`). The
  `deleted N/` prefix is preserved so the lane-retention summary regex
  (`deleted (\d+)/`) still matches.
- `scripts/device-telemetry/prune.py` `main()`: same treatment —
  `expired` counter on `len(old)` per page, line now reads
  `device-telemetry: expired E, deleted D/S (>7d on key ts)`.

## Why
Under the offset race the old line `deleted 0/25313` could appear while
thousands of stale docs still existed (deletes shifting offsets), reading
as a clean collection. `expired` now separates "stale docs seen" from
"docs actually deleted", so delete-batch failures and paging gaps are
visible in the sweep log.

## Verification
- `python3 -m py_compile` both files — clean.
- `python3 -m unittest tests.ada.test_lane_retention` — 28/28 OK.
- Stubbed `post()` smoke: line formats verified for both delete and
  dry-run paths (`expired 2, deleted 0/3`, `expired 3, would delete 3/3`).
- Commit `134daaab0f` on branch
  `dispatch/20261125-123109-prune-old-docs-log-expired-cou` (not pushed).

## How to verify live
Next scheduled sweep output (export-transcripts refresh chain on idc03 /
device-telemetry-prune.timer) will show `expired N, deleted M/S` per
collection; `expired > deleted` indicates delete-batch misses.

lessons:
- lane-retention.py's summary phase regexes `deleted (\d+)/` off the
  sweep line — keep the `{verb} {deleted}/{scanned}` prefix intact when
  reformatting prune output.
