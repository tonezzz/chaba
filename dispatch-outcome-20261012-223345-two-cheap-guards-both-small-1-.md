# Dispatch outcome — guard-card-yaml-syntax-validation-at-wri-a39362

**Card:** Guard: card-YAML syntax validation at write time — render died 2.5h on 3 malformed cards
**Branch:** dispatch/20261012-223345-two-cheap-guards-both-small-1- (commit 71adbc26, not pushed — per rails)
**Result:** all three guards shipped + verified.

## What changed

1. **Write path** (`scripts/board/board-api.py`): `save()` now dumps, `yaml.safe_load`s the result, and refuses before touching the file when it isn't a mapping; writes land atomically via tmp+rename. `load()` rejects non-mapping YAML. All mutating endpoints (`/card /comment /action /request /respond /pipeline`) funnel through `save()`. Bonus fix: `alloc_ref()` resolved `.ref-seq` at import time, so `--selftest` bumped the real counter file — now per-call.
2. **Never reach master** (two layers):
   - `scripts/board/kanban-commit.sh`: after staging, every staged `*.yml` under the generated dirs is `yaml.safe_load`ed; on parse failure the sweep refuses, files the `ops-kanban-commit-guard` alert card naming `file:line:col`, and exits — sibling of the existing conflict-marker guard.
   - `scripts/ssot-validate-all.mjs`: now exits nonzero when any file has errors (it reported but always exited 0, so the `.husky` pre-commit `--staged` gate, `check:ssot`, and the GitHub `ssot.yml` workflow on `docs/ssot/**` pushes could never actually fail). One pre-existing violation fixed: `jobs/ada/2026-10-11-scenario-spend-guard.yml` was missing `title`.
3. **Bonus — render-failure alert** (`scripts/board/board-render-guard.py`, new; `systemd/chaba-board-render.service` now ExecStarts it): runs both renderers, counts consecutive failures in `/tmp/chaba-board-render-guard.json`; 2nd nonzero run in a row upserts `ops-board-render-fail` (cms-auto-style: stable id, review column, note = failing renderer + stderr tail naming the poisoned file). Same failure while open = no churn; changed failure = new comms; recovery = auto-close. Still exits nonzero so the unit shows failed in the journal.
4. **Test** (`tests/test-kanban-commit.sh`): new section F — refuse bad card → alert filed → recover on fix (all pass). Fixture fix: sections A/B/C used to append bare text to `ssot.kanban.yml`, i.e. the test relied on committing corrupt YAML — exactly the class this gate prevents; appends are now comments.

## Verification

- `python3 scripts/board/board-api.py --selftest` → ok (incl. new save/load guard cases)
- `python3 scripts/board/board-render-guard.py --selftest` → ok
- `bash tests/test-kanban-commit.sh` → 27 ok / 1 fail — the `A: parallel commits reached origin` check is a pre-existing parallel-writer race flake (fails identically on unmodified baseline)
- Real guard run on this checkout: rc=0, no alert card; stubbed failing renderer: card on 2nd failure, dedupe on 3rd, auto-close on recovery
- Live gate check in scratch repo: bad staged card reported `bad.yml:4:1: found unexpected end of stream`

## Deploy note

`chaba-board-render.service` now ExecStarts `scripts/board/board-render-guard.py` — deploy the unit together with this merge or ExecStart 404s on hosts whose checkout predates it. Nothing was deployed or pushed from this session.

Trail: `docs/ssot/jobs/kanban/2026-10-12-card-yaml-guards.yml`
