# Dispatch outcome — lesson-qc-sweep (2026-11-09)

Built `scripts/board/lesson_qc.py` — the advisory QC/damping layer over the
self-reported lesson corpus (card lesson-qc-sweep, OPS-1275). Report-only:
clusters duplicates, flags stale refs, detects contradiction candidates,
reports corpus health. Never deletes.

## What changed

- `scripts/board/lesson_qc.py` (new, ~690 lines): harvests the same
  corpus lesson_primer reads — dispatch-outcome-*.md `lessons:` lists,
  docs/ssot/jobs/** lesson fields, card comms — reusing the primer's own
  SIGNAL_RE/COMMS_RE/split primitives via importlib (with fallbacks).
  Checks:
  1. duplicate clusters via token-jaccard >= 0.8 (union-find over an
     inverted index; exact-normalize collapse first; posting lists >800
     skipped — pairs sharing only a ubiquitous token can't reach 0.8)
  2. staleness: `RETIRED_RE` (idc01, tony-dell.taila0626a.ts.net —
     periodic-review constant per lesson-primer-scoring-fixes convention),
     `missing-path` repo-existence checks gated by the card's declared
     `action.repo` (cross-repo paths are unverifiable — not flagged),
     `renamed-repo` for unknown CascadeProjects/<name> checkouts
     (dispatch-wt-* worktrees exempt)
  3. contradiction candidates: same top-3-content-token signature
     (rarest-first) + opposing directive markers (never/do-not vs
     must/always)
  4. health: per-source counts, growth vs
     `~/.local/share/board/lesson-qc-state.json` (`--state`/`LESSON_QC_STATE`
     override), self-seeding compliance (% outcome docs with parseable
     `lessons:`, plus since-2026-10-09 TASK_RAILS slice)
- `tests/board/test_lesson_qc.py` (new): 5 tests — harvest+str-comm
  tolerance, dup clustering, stale flags incl. repo gate, contradiction
  pairs, write+convergent-idempotency.
- `scripts/devin/devin-dispatch-watch.sh`: best-effort tail step calling
  the script — SAME mechanism render-handoff-inbox.py uses (chosen over a
  standalone timer because the corpus grows exactly when dispatches land,
  which is what the watcher polls; documented in the script docstring,
  the shell comment, and the generated yml `invocation` field).
  `LESSON_QC=0` disables, `LESSON_QC_OPS_EVENT=0` mutes the event emit.
- Outputs landed: `docs/ssot/jobs/kanban/2026-11-09-lesson-qc.yml`
  (tracked) + `reports/lesson-qc-2026-11-09.md` (generated; reports/* is
  gitignored by convention). Ops-event doc emitted to ada-ha-events-tony
  (kanban-dispatch ops_event shape; fingerprint+24h dedup so the 5-min
  watch cadence can't spam).

## Result — live corpus (1883 lines: 52 outcome / 47 jobs / 1784 comms)

- 57 flags: 45 dup clusters, 12 stale refs, 0 contradiction pairs.
- Top clusters are auto-generated comms repeats: ops-local-conflict-guard
  x605, merge-sweep verified-gate x188, timer-alert x139.
- Stale: 8 retired-ref:idc01 + 1 retired-ref dell-tailnet + 3 genuinely
  missing repo files (ssot.messaging-lanes.yml, an opencode-cline report,
  the 2026-11-07 ops-health job yml).
- Self-seeding compliance is LOW: 22/355 outcome docs (6%), and still
  only 22/311 (7%) for docs after the 2026-10-09 TASK_RAILS rule — the
  corpus barely grows from self-seeding; comms dominate (1784/1883).
- Two corpus bugs found incidentally: (a) kraut-rain-events +
  kraut-weather-bakeoff carry a bare-string `comms` entry that CRASHES
  lesson_primer._comms_candidates (warn-only in production → primers
  silently lose all comms); (b) QC's own yml avoids lesson-key field
  names so it can't re-ingest itself.

## Verify

- `python3 -m unittest tests.board.test_lesson_qc` — 5/5 pass.
- Live run: `python3 scripts/board/lesson_qc.py` — prints one-line
  summary; artifacts under docs/ssot/jobs/kanban/ + reports/.
- Idempotent: 3rd consecutive run reports `job-yml=unchanged,
  report=unchanged`; ops-event deduped by fingerprint.
- idc01 flag present (verify requirement): 8 corpus lines flagged.
- `bash -n devin-dispatch-watch.sh` clean; watch tail guarded by
  `[ -f ]` + `|| true` — never breaks the watcher.

lessons:
- primer crashes on bare-string comms entries (kraut-rain-events, kraut-weather-bakeoff) — any consumer of card comms must type-check entries; primer loses all comms silently when it hits one
- self-seeding is failing: only 7% of post-2026-10-09 outcome docs carry a parseable lessons: list — rails bullet exists but sessions mostly skip it; QC now measures it
- missing-path QC must gate on the card's declared action.repo — ada-voice/ada-pi paths in comms are unverifiable from the chaba checkout and were 60% of first-run flags
- byte-identical idempotency needs volatile fields (prev_at timestamps) kept OUT of regenerated artifacts — put them in the state file instead
