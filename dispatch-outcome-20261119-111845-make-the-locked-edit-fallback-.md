# Dispatch outcome — board-janitor-locked-edit-atomic-write-db7bed

## What was found

The core fix already existed on master: commit `d52179fd5a` (2026-11-19
08:32 ICT, "kanban: atomic card writes everywhere — card_io helper")
introduced `scripts/board/card_io.py` (`atomic_write_text` =
tmp-in-same-dir + flush + fsync + `os.replace` + dir fsync;
`atomic_dump_card` adds refuse-before-touch round-trip validation) and
converted merge-sweep's `locked_edit` fallback — the exact path that tore
three cards during the idc03 ENOSPC window — plus board-api.save/inbox,
kanban-commit.sh embedded writes, merge-card-yaml driver, kanban-dispatch,
all janitor sub-sweeps, and most focus-inbox writers.

The card's two prior dispatch failures (10:16, 11:05) were provider
rate-limit exits (~15s wall clock each), not work failures.

## Gap audit — what this dispatch changed

A full re-audit of every `write_text`/`open(...,'w')` touching card or
focus-inbox YAML found two survivors the earlier commit missed:

1. **`scripts/ci/card-pipeline.py`** — `FileSink.flush()` did a direct
   `self._path(cid).write_text(yaml.safe_dump(...))` on
   `docs/ssot/kanban/cards/*.yml` under `/tmp/board-api.lock`. Now calls
   `card_io.atomic_dump_card` (same dump kwargs: unicode, unsorted,
   width 110).
2. **`scripts/report/report-watch.py`** — `heal_item()` did a direct
   `p.write_text(yaml.safe_dump(...))` on focus-inbox YAML (the other
   three inbox writers in the same file were already atomic). Now calls
   `card_io.atomic_write_text`.

Plus the missing committed test:

3. **`tests/board/test_card_io_atomic.py`** (new) — fault-injection
   coverage: ENOSPC at fsync, kill at os.replace, success leaves
   complete new content with no `*.tmp` leak, inode-level proof that
   readers see old-or-new (rename, never in-place), `atomic_dump_card`
   refuse-before-touch, and FileSink.flush fault injection proving a
   mid-flush failure leaves the card byte-identical.

## Verification

- `pytest tests/board/test_card_io_atomic.py` — 8/8 pass
- `pytest tests/board` — 681 passed, 8 subtests (12 min, no failures)
- `card-pipeline.py --selftest` — ok (exercises FileSink end-to-end)
- `merge-card-yaml.py --selftest` — ok
- kanban-commit YAML gate equivalent: `yaml.safe_load` on all **976**
  `docs/ssot/kanban/cards/*.yml` — 0 bad
- board-janitor.py confirmed read-only on cards; every janitor sub-sweep
  (merge/answer/request/lab-review/review-digest) writes via `card_io`;
  shell-side paths (`git-safe-pull.sh`, `kanban-sync.sh`, `promote-lane.sh`,
  `install-hooks.sh`) only read or file-level copy card YAML.

## Notes / collateral

- Accidentally ran `report-watch.py` once while probing (`--help`
  doesn't exit — it's a watcher). It created 15 focus-inbox items and
  healed 2 via the new atomic path before being killed; all pollution
  reverted (`git checkout` + rm of the `2026-11-19-112049-report-watch-*`
  files). Working tree contains only the two script edits + new test.
- Not pushed, not committed to master — dispatch worktree only.

lessons:
- `report-watch.py` has no `--help`/dry-run arg guard — running it with
  any args executes a live tick that writes focus-inbox items; compile-check
  with py_compile instead.
- The `d52179fd5a` atomic-write commit missed scripts outside `scripts/board/`
  and `scripts/ops/` — grep the WHOLE repo (scripts/ci/, scripts/report/)
  for `write_text` on card/inbox paths, not just the board dir.
- `card_io.atomic_write_text` patches cleanly via `mock.patch.object(
  card_io.os, "replace"|"fsync")` — fault injection needs no real ENOSPC.
