# Dispatch outcome — guard-card-yaml-syntax-validation-at-wri-a39362 (re-dispatch)

**Card:** Guard: card-YAML syntax validation at write time — render died 2.5h on 3 malformed cards
**Branch:** dispatch/20261022-194658-two-cheap-guards-both-small-1- (commit f7a90fb4, not pushed — per rails)
**Result:** all three guards verified already merged and functional from the 2026-10-12 dispatch; found and fixed one adjacent silent-failure bug in git-safe-pull.sh. Test suite now 36/36 (was 35/36).

## Why this ran again

The 2026-10-12 dispatch (commit 71adbc26, since merged) shipped all three guards, but the card stayed `backlog`/`action.status: queued`, so the runner re-claimed it. This session verified the landed state instead of re-implementing.

## Verified (no changes needed — already in tree)

1. **Write path** (`scripts/board/board-api.py`): `save()` dumps, `yaml.safe_load`s the result, refuses before touching the file if not a mapping; atomic tmp+rename. `load()` rejects non-mapping YAML. All mutating endpoints funnel through `save()` — `/card` (via `do_create` line ~1097), `/comment`, `/action`, `/request`, `/respond`, `/pipeline`, `/patch-relay`. `--selftest` passes.
2. **Never reach master** (three layers): `.husky/pre-commit` yaml.safe_loads every staged `docs/ssot/*.yml` + runs `ssot-validate-all.mjs --staged`; `kanban-commit.sh` refuses staged unparseable YAML and files the `ops-kanban-commit-guard` alert; `.github/workflows/ssot.yml` runs the validator on every `docs/ssot/**` push — and the validator now exits nonzero on errors (verified: rc=1 on a deliberately malformed card file).
3. **Bonus — render-failure alert** (`scripts/board/board-render-guard.py`, ExecStart of `systemd/chaba-board-render.service`): two consecutive nonzero render runs upsert `ops-board-render-fail` (stable id, review column, note names failing renderer + stderr tail); same failure = no churn, changed = comms, recovery = auto-close. `--selftest` passes.

## Changed this session

- `scripts/git-safe-pull.sh`: `exec {SAFE_PULL_LOCK_FD}>"$BOARD_LOCK" 2>/dev/null` is a bare exec — the `2>/dev/null` **permanently** redirected the script's stderr, silently swallowing every diagnostic after the lock open ("board lock held — pulling anyway", untracked-collision moves, "needs manual resolution", reconcile output). The lock still worked; only the logging died — the same silent-failure class this card exists to prevent. Wrapped the exec in a brace group so suppression scopes to the open attempt only; fd lifetime and `||` fallback unchanged. Caught by `tests/test-kanban-commit.sh` section G ("held lock waited then bypassed with a log line").
- `docs/ssot/jobs/kanban/2026-10-22-safe-pull-stderr-swallow.yml`: trail entry.

## Verification

- `bash tests/test-kanban-commit.sh` → **36/36 pass** (was 35/36; the G log-line check was the real bug, not a flake)
- `python3 scripts/board/board-api.py --selftest` → ok
- `python3 scripts/board/board-render-guard.py --selftest` → ok
- `node scripts/ssot-validate-all.mjs` on a deliberately malformed card → rc=1, error reported
- Manual repro of the stderr swallow confirmed silent before the fix and loud after

## Board / card note

Posted a board comment summarizing all of the above. The card's work is complete — it can move to done once the merge lands.
