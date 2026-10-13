# Dispatch outcome — calendar-write-idempotency

**Card:** `calendar-write-idempotency` — dedup identical creates (double-write bug)
**Runner:** idc02 · **Branch:** `dispatch/20261013-112958-calendar-create-event-in-backe` · **Commit:** c3ca1693

## What was found

`calendar_create_event` (named in the card at `backend/tool_runner/calendar.py`)
lives in the **ada-pi repo** (`tonezzz/ada-pi`), not chaba — this worktree only
carries the `integrations/ada-pi/` drop-in area, which is the established
pattern for staging ada-pi changes from a chaba dispatch. The tool_runner
method is a thin wrapper; every create path — `calendar_write action=create`,
the absorbed `calendar_create_event` alias, and any future non-tool caller —
funnels through `CalendarService.create_event` in
`backend/calendar_providers.py`, which is also the only layer that already
knows the resolved `(provider, calid)` write target. The guard was therefore
implemented there, with a docstring pointer added on the tool_runner wrapper.

## What changed (in this worktree, commit c3ca1693)

- `integrations/ada-pi/backend/calendar_providers.create-dedup.patch` — unified
  diff vs ada-pi `main` @ `d166794` (3 files, +173/−3):
  - `backend/calendar_providers.py`: `create_event` → `_find_duplicate` lists
    the target calendar's day window before writing; on normalized title +
    identical-start match returns the existing event as
    `{..., dedup: true, existing: <qualified id>}` instead of creating.
    Normalization: NFC + casefold + collapsed whitespace on titles (Thai
    combining sequences compare equal), bare dates compare by day, datetimes
    by absolute instant (`+07:00` vs `Z` spellings match). A failed dedup list
    propagates (loud-fail, same rule as reads) — a blind create is how the
    double-write happened.
  - `backend/tool_runner/calendar.py`: docstring noting the service-level dedup.
  - `tests/test_calendar_providers.py`: 7 new tests + `FakeProvider` now
    reflects creates into `list_events`.
- `integrations/ada-pi/README.md` — Drop 3 section (install runbook + contract).
- `docs/ssot/jobs/ada/2026-10-13-calendar-write-idempotency.yml` — job trail.

The companion fix named in the card (dead `e468a444` calendar removed from
`ssot.apps.ada-calendar.yml`) was already in this worktree's HEAD as commit
15204342 — verified absent from the yml.

## Result / verification

- Verified on a `/tmp` clone of ada-pi `main` @ `d166794` with the patch
  applied: `tests/test_calendar_providers.py` **49/49 pass** (7 new: dedup hit,
  title/instant normalization, all-day, different-calendar scope, no-match
  still creates, dedup-read failure loud with no blind write, end-to-end
  `calendar_write` double-invoke through `ToolRunner.execute` → one provider
  write, second call returns `dedup: true`). `scripts/tool-lint.py` clean.
- `git apply --check` verified clean against pristine `d166794`.
- **Not deployed** (no-push rule): to land it, `git apply` the patch in an
  ada-pi worktree, run the deploy-ada.sh gates, deploy. After deploy, repeating
  an identical confirmed create returns the same event id with `dedup: true`
  and writes nothing new.
- Card comms posted; board updated.
