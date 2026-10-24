# Dispatch outcome — pattern library: leak guard + 3-way router + mine-back (OPS-0809)

Card: `pattern-library-coding-research` · runner: tony-omen · branch:
`dispatch/20261024-174715-p1-pattern-mine-leak-safe-terr` (2 commits, not pushed)

## What was produced

- **`scripts/pattern-lib/`** (in-repo, durable): the whole P1–P5 pipeline
  codified — `leak_guard.py` (banned commits = children of each task.yaml
  `repo.ref` + extras), `mine_patterns.py` (fix-class miner, guard-aware),
  `push_pattern.py` (`/v1/add` upsert, guard-refuses banned),
  `router.py` (arm3: retrieve → codemod-if-registered → hint-injected
  agent → plain agent, per-task leak filter, codemod-skip fall-through,
  doc hydration), `run_arm.py` (P4 driver: clone@ref via bare-mirror
  cache + `.venv-verify` via uv + same score.py + results jsonl),
  `mine_back.py` (P5 verified-fix → pattern, guard-enforced),
  `codemods.json` registry + durable t1 codemod copy.
- **`~/evals/patterns/leak-guard.json`** on dell — banned set:
  t1 `f8a5d9c`, t2 `5c5d3c5`, m1 `c0850f0`, m2 `497b982` (auto-derived).
- **`docs/ssot/jobs/bench/2026-10-24-pattern-lib-guard-router.yml`** —
  job record with results + bugs-fixed.
- **`mine-mddb.jsonl` sanitized** — it carried c0850f0/497b982 (the m1/m2
  reference fixes) as mining candidates; store itself was clean.

## Bugs found and fixed in the pipeline (this is the real session value)

1. **Leak filter was a no-op**: banned SHAs stored 12-char, pattern
   records carry 7-char commits — `in`-comparison never matched. Fixed
   with prefix-safe matching in router, push_pattern, mine_patterns.
   Verified: t1 strict now drops `pat-elevated-geom-covered-by`,
   mine_back refuses c0850f0, miner skips both m1/m2 commits.
2. **Codemod SKIP ended the arm as success**: t2 retrieved the t1
   pattern @0.685, ran its codemod, got "SKIP count=0", and returned
   without trying the agent. Fixed: fall through unless output shows
   PATCHED — verified live on the t2 rerun.
3. **Hint arms ran gutted**: `/v1/vector-search` returns `contentMd:""`
   even with include_content — hints contained trigger text only, never
   the Transform. Router now hydrates via `/v1/get`; push_pattern writes
   `meta.transform`.
4. leak_guard repo-name matching missed url-basename aliases; run_arm
   parallel bare-mirror clone race — both fixed.

## Bench results (arm3, flash-lite, leak-guarded)

| task | arm | result | latency | note |
|---|---|---|---|---|
| t1 | 3 strict | **5/7** | 176s | own pattern dropped; wrong-domain hint; covers near-miss (same as arm0) |
| m1 old verifier | 3 | 0.0 | 80s | zero impl edits; coupled verifier build-fail |
| m1-behavioral | 0 | 0.5 | 96s | zero edits |
| m1-behavioral | 3 hint | 0.5 | 138s | zero edits — hint-neutral |
| t2 | 3 | 0/0 | 352s | fall-through works; t2 gate is the known no-op |

Findings: (a) retrieval noise — a 4-pattern store scores >0.35 on any
prompt; needs class/repo gating or higher threshold before hint fires;
(b) flash-lite produces ZERO implementation edits on m1/t2 regardless of
hint — lane agency is the bottleneck on non-t1 tasks, not retrieval;
(c) the t1 7/7 codemod result remains a warm bootstrap demo — honest
held-out t1 for this lane is ~5/7.

## How to verify

- Guard: `ssh tony-dell 'cat ~/evals/patterns/leak-guard.json'` and
  `python3 ~/evals/patterns/mine_patterns.py --repo-name mddb-fork
  --repo-dir ~/CascadeProjects/mddb-fork --guard ~/evals/patterns/leak-guard.json`
  → stderr shows `2 banned skipped`.
- Ledger: `ssh tony-dell 'cat ~/evals/results/arms.jsonl'`.
- Code: `scripts/pattern-lib/` on this branch (commits 91478edf8, 71df8d6fb).
- Card comms carry the running summary.

## Caveats / next

- Pattern store is still 4 records — too thin to measure threshold
  honestly; expand mining (mddb-fork deep history) next.
- Suggest class-gating retrieval (repo/lang meta match) before the 0.35
  score threshold — kills the wrong-domain-hint failure mode observed.
- m1/m2 need behavioral verifiers (m1-beh done; m2 pending per prior
  session) and t2 needs a verifier at all — bench remains noisy until
  gates are honest.
