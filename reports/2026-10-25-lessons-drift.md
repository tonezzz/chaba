# lessons-drift — first run (2026-10-25)

New check: `scripts/lessons-drift.py` — read-only audit of every WP
`lesson` post via board-api `/lesson` (op=list + op=get; no WP creds).
Extracts repo-path source references from lesson content and compares
each source's last `git log -1 %cs` against the lesson's own re-file
stamp (meta.updated → learned_at → WP modified).

Raw rows: `reports/2026-10-25-lessons-drift.json` (77 lessons audited).

## Result

| flag | count | meaning |
|------|-------|---------|
| drift | 1 | `lesson-9bc73936498c` (Ada Nest — NCM report) cites `README.md`, committed 2026-10-25 > filed 2026-10-24 — real staleness signal (and a pointer-precision smell: README.md is a weak source ref) |
| source-gone | 36 | referenced path absent from the canonical repo |
| no-repo-source | 38 | no repo-path reference in content (mostly legit — chat/voice lessons) |

## Findings

- **`docs/tools/ai-workforce-eval.md` is a broken pointer in ~28
  lessons.** `git log --all` shows the file was never committed — the
  lessons were filed from a working doc that never landed in the repo
  (or was renamed). Same for `docs/tools/agentic-ai-coding-ides.md`,
  `docs/tools/3d-models-from-map-data.md`, `docs/function-calling.md`,
  `docs/devin-macbook-ipv4-outage.md`, `apps/webgpu-bench/job.json`.
  A lesson whose source doc doesn't exist can't be re-verified — these
  should either get the doc committed (e.g. under `docs/kb/`) or have
  the pointer corrected at next re-file.
- The check is cheap (~30s for 77 lessons) and read-only — safe for a
  periodic audit lane alongside `lessons-audit.py` (which checks
  level/review-date/thinness, not source freshness).

## Semantics / limits

- `drift:` = source committed after the lesson's last re-file. Date
  granularity (YYYY-MM-DD) — same-day commits don't flag.
- `source-gone:` = path not in repo HEAD. Doesn't distinguish
  moved-vs-never-landed vs external-doc pointers.
- `--strict` exits nonzero on drift (gate-able). `--slugs` audits a
  subset. `--repo` overrides the checkout used for source lookups —
  run it where the checkout is fresh (it answers "is the lesson stale
  vs the repo", so the repo must be current).

## Verifier / rollback

- Verifier: this report + JSON — counts match `op=list` (77). Re-run:
  `python3 scripts/lessons-drift.py --out <file>`.
- Rollback: new read-only script; delete to retract. Nothing else
  depends on it yet — wiring it into a timer lane is a separate card.
