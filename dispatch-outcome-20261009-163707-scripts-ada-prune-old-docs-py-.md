# dispatch outcome — fix-review-refresh-prune

## Root cause
Not MDDB slowness. `scripts/ada/prune-old-docs.py` paginated `/search` at
`limit=100` over ~261k host-logs docs (ops:11026 = 120,530 + stale leader
copy on :11023 = 140,956). Page latency is ~0.7s regardless of offset
depth → list phase alone ≈ 2,650 requests ≈ 30 min > 600s subprocess
timeout inside `export-transcripts.py`. idc03 load was normal (load ~3,
mddbd ~6% CPU). At fix time essentially nothing was expired — the cost
was pure scanning; per-doc `/delete` would have made it far worse once
backlogs existed.

## Fix (commit b9d1c761 on dispatch branch)
- `PAGE_SIZE` 100→5000 — verified ~1s/page even at offset 100k on both DBs.
- Deletes via `/v1/delete-batch` in chunks of 1000 (was one POST per doc).
- Per-collection elapsed seconds now printed.
- `skip += kept` shift-compensation and meta-key policy semantics unchanged.
- `export-transcripts.py` subprocess timeout left at 600s — now honest
  ~7× headroom rather than a mask; batch commits make the sweep naturally
  resumable anyway.

## Measured on tony-omen
- `--dry-run`: 82s total (was >600s killed). host-logs 40s+40s; other
  collections <1s.
- Real run: 62s, deleted 70 stale leader docs, exit 0.
- `ada-review-refresh.service` manual run: **status=0/SUCCESS, 5m01s
  wall** (vs 12m27s FAIL this morning). Prune line in journal:
  `host-logs: deleted 0/140886 (>14d on ts) in 33s`.

## Notes
- omen's `~/CascadeProjects/chaba` has the patched script as a local
  modification (dispatch branch unmerged) — `git checkout` it once the
  commit reaches master, or just let the merge overwrite.
- `/search` ignores `rangeMeta` (FTS-only); a wildcard `/fts` probe over
  host-logs ran 59s then dropped — don't use FTS for retention sweeps.
- Job trail: `docs/ssot/jobs/ada/2026-10-09-prune-old-docs-paging-fix.yml`
- Board updated with findings + verification on card
  `fix-review-refresh-prune`.
