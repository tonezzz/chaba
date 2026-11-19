# Outcome — torn kanban card write investigation (2026-11-19 ~03:00 ICT)

## Root cause (named, with log evidence)

**Trigger:** idc03 disk hit ENOSPC at ~02:55:41 ICT. `mddb-backup` ran
`podman cp` streaming a ~19GB uncompressed mddb-ops DB
(`mddb-ops-20261119-0237.db`, partial) onto a disk already 99% full.
Journal evidence: mddb-backup mkdir "No space left on device", podman
"database or disk is full" container-state writes, `zones.json` Errno 28,
runner-agent refusing claims "disk headroom 0MB". journald then dropped
all messages 02:56:18 → 03:37 — exactly the tear window.

**Writer:** board-janitor's 02:56 tick ran `merge-sweep` as its first
sub-check inside the journal gap. merge-sweep's `flag_once(fetch_failed)`
→ `stamp()` → `locked_edit()` did a **direct `p.write_text()`** on card
files (no tmp+rename) and ENOSPC tore them mid-scalar.

Byte-level proof: the uncommitted torn blob for
`trade-lesson-workflows-automation.yml` contains
`action.sweep.fetch_failed: 2026-11-19 02:57` — a merge-sweep stamp that
was never committed. The other two torn blobs are exact HEAD prefixes
cut at page boundaries (12288 = 3×4K, 8192 = 2×4K bytes) — the signature
of a buffered write cut mid-flush.

**Not the writers:**
- `board-api.save()` was already tmp+rename — its ENOSPC failures left
  only the 0-byte `.yml.tmp` shells (02:57–03:04) seen at repair time,
  plus HTTP 500s that pushed merge-sweep into its direct-write fallback.
- `focus-dispatcher-overnight` fired at 03:00 but never touches cards
  directly; its own `overnight-status.json` is 0 bytes at 03:00 — victim,
  not writer.
- `kanban-dispatch.timer` disabled on idc03 since Nov 17.

**Blast radius:** kanban-commit's YAML gate correctly refused the
malformed staged cards from 03:48 until manual repair at 08:12
(commit `423baed`); board-api readers failed `yaml.safe_load` → 503
"canonical card store unavailable".

## Fix implemented

New shared helper `scripts/board/card_io.py`:

- `atomic_write_text(p, text)` — serialize → `<name>.<pid>.tmp` in the
  same dir → flush + `os.fsync` → `os.replace` → fsync dir. On failure
  the tmp is removed and the target untouched. fsync-before-rename also
  covers the delayed-allocation case where rename succeeds but the tail
  is lost when writeback hits ENOSPC.
- `atomic_dump_card(p, card, **kw)` — `yaml.safe_dump` + refuse-before-
  touch round-trip validation (same contract as board-api.save) →
  `atomic_write_text`.

All card/focus-inbox mutators now route through it (~30 call sites):
board-api (`save`, inbox write — now with fsync), merge-sweep
`locked_edit` (the proven tear path), kanban-commit.sh's embedded
alert/recover card writes, merge-card-yaml (`card-union` driver %A
write), kanban-dispatch, answer/request/lab-review sweep, review-digest,
reconcile-local-conflicts, runner-fleet-health, deploy-preflight,
ref-backfill, board-invariants, card-column-guard, backfill-briefs,
board-render-guard, kanban-stats, audit-hosts, command-truth,
lifecycle-check, disk-trend-watch, cms/gev/vcast-auto-health,
logs-kanban, kanban-act, report-watch, backlog-spec-enrich,
check-serve-config, focus-sweep, session-audit, focus_dispatcher
intake.

Commits on `dispatch/20261119-081822-investigate-torn-truncated-kan`:
`880df7caf4` (first batch, auto-committed at compaction) + `d52179fd5a`
(remaining writers + card_io.py + incident record). Nothing pushed,
nothing deployed — the served checkout keeps its current code until the
dispatch merge lands.

## Verification

- `python3 -m py_compile` all modified files — OK; `bash -n
  kanban-commit.sh` — OK.
- All 19 modified modules import cleanly (incl. `focus_dispatcher.actions`
  as a package).
- `merge-card-yaml.py --selftest` OK; `reconcile-local-conflicts.py
  --selftest` OK.
- Functional test of `card_io`: happy-path write leaves no `.tmp`;
  injected mid-write failure leaves target byte-identical with tmp
  cleaned; non-mapping dump refused before the file is touched.
- Audit: no remaining direct `write_text` targeting
  `docs/ssot/kanban/cards/` (only test fixtures and non-card artifacts).
- Incident record filed:
  `docs/ssot/jobs/board/2026-11-19-torn-card-write-enospc.yml`
  (passed the repo's SSOT pre-commit validation gate).

## Follow-ups for Tony (flagged in the board comment)

- idc03 still ~99% full (3.7G free); the 19GB partial
  `mddb-ops-20261119-0237.db` is still on disk — deletion is Tony's call,
  and mddb-backup should check headroom before streaming.
- `overnight-status.json` writer is non-atomic too (minor).
- `.yml.tmp`/`*.tmp` aren't gitignored — harmless now, cheap insurance.
