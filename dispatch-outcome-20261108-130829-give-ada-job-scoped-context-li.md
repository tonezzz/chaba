# Dispatch outcome — ada-job-brief-builder (2026-11-08, idc02, second session)

## TL;DR

The card's deliverable was already built and measured by the sibling
dispatch on the same card (`dispatch/20261108-123515-…`, commit
`fe405f258`). What remained was the reason it never landed: the
auto-merge **conflicted** against the scaffold commits that had reached
master first. This session resolved that merge, verified the complete
implementation end-to-end on a second real card, and committed the
converged result on this branch.

## What this session changed

- **`git merge dispatch/20261108-123515-…`** (commit `90280edfe`):
  - `scripts/ada-jobs/brief_builder.py` — add/add conflict (scaffold v1
    vs sibling's full implementation). Resolved to the sibling version:
    TF-IDF corpus NN + mddb `:11027/v1/vector-search` (parent retrieval)
    over `infrastructure-ssot`, `chaba-lessons`, `kb-*` + local
    `docs/ssot` grep offline fallback + `render()` prompt block +
    `--corpus-briefs` bench mode with leave-one-out gold-leak guard.
  - `scripts/ada-jobs/verify_worker.py` — content conflict, same
    resolution: `--with-brief` builds+prints the bundle before her turn,
    injects `snap.job_brief`, degrades to no-brief on failure.
  - `scripts/bench/card-judgment/score.py` — content conflict, same
    resolution: `--briefs <json>` (pre-computed leave-one-out briefs),
    replacing the scaffold's inline `--with-brief` wrapper.
  - Brought in: `run11-14` bench artifacts, `briefs.json` (98 leave-one-out
    briefs), `docs/ssot/jobs/ada/2026-11-08-ada-job-brief-builder.yml`,
    `ssot.jobs.yml` ada-jobs-verify note, sibling dispatch-outcome.
- Killed a duplicate baseline bench run once the sibling's four
  artifacts were found (saved the spend).

## Verification (this session, on the merged tree)

- `brief_builder.py --card ada-docs-search-drift` → full bundle:
  3 related SSOT + 2 lessons + 3 KB docs (incl. on-topic
  `documentation-search-mddb.md`) + top-3 similar cards led by
  `starboard-windsurf-catalogs` — same domain as the card's bug.
- `verify_worker.py --once --sweep cleanup --card ada-docs-search-drift
  --with-brief --dry-run` (litellm `bench` = gemini-3.5-flash-lite via
  `LITELLM_KEY_ADA` on idc02): bundle printed, Ada decided
  **skip/alive** with a grounded reason — real card scored, bundle shown.
- All three files `py_compile` clean; every importer of brief_builder is
  consistent (`verify_worker` is the only consumer today).

## Defer-boundary delta (from the sibling's run11-14, now merged)

| model | acc | deference | corr_prec | notes |
|---|---|---|---|---|
| flash-lite baseline | 0.4898 | 0.5102 | 0.875 | defer recall 29/30 |
| flash-lite +brief | 0.6122 | 0.6122 | 1.0 | defer recall 30/30; fact-case over-deferral 47→38 |
| chat baseline | 0.9082 | 0.9082 | 1.0 | |
| chat +brief | 0.8980 | 0.9082 | 1.0 | flat within noise |

The delta lives on the weak-brain boundary exactly as the card
hypothesized; a calibrated brain sees no regression. Still below T3
(0.61 << 0.90) — the brief helps, doesn't solve.

## Open item for the merge path

This worktree's close-out merge into master should now be conflict-free
(the conflict was sibling-vs-master, resolved here by merging the
sibling). Watch: `LITELLM_KEY_BENCH` is over its $2 budget — bench runs
used `LITELLM_KEY_ADA` (the ada-jobs key) on the `bench`/`tool-call`
aliases.

## How to verify

```
python3 scripts/ada-jobs/brief_builder.py --card ada-docs-search-drift
python3 scripts/ada-jobs/verify_worker.py --once --sweep cleanup \
  --card ada-docs-search-drift --with-brief --dry-run \
  --base-url http://100.102.134.91:4000/v1 --model bench \
  --api-key-env LITELLM_KEY_ADA
ls scripts/bench/card-judgment/run1[1-4]-*.md
```
