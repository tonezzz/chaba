# Dispatch outcome — board-api-card-set-non-dispatch-guard

## What was found

The card's spec items 1 and 2 were already landed on master by an
earlier dispatch (commit `132c1119af8` "OPS-0007: /card-set refuses
non-dispatch cards; cache valid_lanes() on file mtime", deployed to
idc03 per card comms 2026-11-23 11:28). This worktree contains that
commit, so the guard and the cache were verified present rather than
re-implemented:

- `do_card_set` refuses (ValueError → 400) when the card has no action
  block or `action.type != "dispatch"` — before `_ensure_act` could
  fabricate an action block (`scripts/board/board-api.py`, ~line 2548).
- `valid_lanes()` is cached on `_VALID_LANES_CACHE` keyed on the lane
  catalog file's mtime; `_retired_lanes()` is only reachable through
  `valid_lanes()`, so the YAML parse is covered.

## What this run added (spec item 3 — selftest gap)

The merged selftests covered refusal but not the remaining spec asks.
Added in `scripts/board/board-api.py` `_selftest()`:

- No-action and script-typed cards now assert **untouched** state after
  refusal (no fabricated `action` block, no comms appended).
- New mtime-cache test: redirects `LANES_FILE` to a tmp catalog,
  verifies a rewrite at the same mtime serves the stale cached set and
  an `os.utime` mtime bump forces re-parse (a `free_lane` marked
  `status: retired` drops out of `valid_lanes()`). Cache and path are
  restored afterward.
- Supporting refactor: the catalog path was extracted to module
  constant `LANES_FILE` (used by both `_retired_lanes()` and
  `valid_lanes()`) so the selftest can redirect it, matching the
  existing `CARD_DIR`/`LOCK`/`DISPATCH_TASKS` redirect pattern.

Also fixed unrelated suite rot that blocked "existing tests still
pass": `tests/board/test_codemod_lane_gate.py::_load_card` now falls
back to `cards/archive/` — fixture card
`idc03-gemini-ollama-proxy-paid-fallback-2fa021` was archived by a
board-api action on 2026-11-23 and the test 500'd on the missing live
file.

## Result

- `python3 scripts/board/board-api.py --selftest` → `selftest ok`
  (includes the new guard and cache assertions).
- `pytest tests/board/` → 193 tests, all pass (the one pre-existing
  failure was the archived-fixture rot, now fixed).
- No deploy — worktree only, per rails.

## How to verify

    python3 scripts/board/board-api.py --selftest
    python3 -m pytest tests/board/ -x -q

Live (already verified by the earlier deploy): POST /card-set on a
non-dispatch card → 400 "card has no dispatch action — arm it with
/card first".

lessons:
- Re-dispatches can pick up already-merged cards: check `git log` for
  the landing commit before re-implementing — the delta may be only
  test coverage.
- Tests pinned to live kanban card ids rot when the board archives
  cards — `_load_card` needs a `cards/archive/` fallback.
- board-api writes serialize under /tmp/board-api.lock with a bounded
  wait — a /comment POST can 503 "lock saturated"; retry, don't
  shorten the client timeout below LOCK_WAIT_S (25s).
