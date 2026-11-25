# dispatch-outcome: m1-behavioral fixture activation + skip accounting

Card: `m1-behavioral-fixture-activation-and-skips` (ref OPS-1301). Consumer is
on tony-dell (`~/evals/tasks/m1-behavioral`), edited via ssh; repo-side trail
in `docs/ssot/jobs/bench/2026-11-25-m1-fixture-activation.yml`.

## What changed (all on tony-dell `~/evals`)

- **Hook reviewed then activated.** `c66b563c3c3e08c2f1a293d6dc5217b6d94bc8f9`
  (idc02 mddb-fork, `dispatch/20261025-055220-m1-add-a-stream-state-test-hoo`,
  based on pinned `ed1ff116`) adds `connected atomic.Bool` wired in
  `replicate()`/`disconnect()` plus `SetStreamStateForTest(connected, lagMs,
  lastAppliedAt, appliedLSN)`; `IsHealthy`/handler semantics untouched.
  Pushed the branch to `tonezzz/mddb` — dispatch/* branch only, no promotion.
- **`task.yaml`**: `repo.ref` bumped `ed1ff116…` → `c66b563c…` (backup
  `/tmp/task.yaml.bak`). All four held-out cases now execute.
- **`verify/score.py`**: `--- SKIP:` lines now count in the denominator
  (`passed+failed+skipped`), are named in `checkpoints.tests.skipped_names`
  and the summary, and set `qualified=false` unless zero skips and all pass.
  Additive keys only; marker schema unchanged.
- **`verify/test_score.py`** (new): 4 stub-`go` regression tests —
  `pytest` → 4 passed.

## Verification

- `score.py` on `/tmp/m1hook/parent` (c66b563, no fix): **0.5 (2/4)**,
  0 skips — idle test FAILs on time-based IsHealthy as designed.
- `score.py` on `/tmp/m1hook/fix` (c0850f0 + cherry-picked hook `520ac078`):
  **1.0 (4/4), qualified=true**.
- Skip accounting: 3 pass + 1 skip scores 0.75 (not 1.0); skips named.
- Historical evidence unchanged: `results/20261109_022656_b016d7.*` mtimes
  still 2026-11-09; scores not rewritten. The independent DeepSeek M1
  five-state/idle-24h evidence remains separate.
- Injected `zz_heldout_*` cleaned from both workspaces post-run.

## Not done (per card)

No paid model reruns, no stage/provider/code promotion, no threshold
relaxation. `~/evals` is not under git — changes exist only on dell.

lessons:
- The m1 hook commit lived only on idc02's mddb-fork; activation required an
  explicit `git push origin <dispatch-branch>` before dell could fetch it.
- c0850f0 (real fix) already wires `connected` identically to the hook —
  cherry-picking the hook onto the fix conflicts only on adjacent method
  hunks; union-resolve keeps both.
- score.py skip accounting is best regression-tested with a stub `go`
  binary on PATH — no toolchain or paid run needed.
