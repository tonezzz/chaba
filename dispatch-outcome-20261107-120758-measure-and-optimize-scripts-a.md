# dispatch outcome — measure-and-optimize nest-worker.py (jevnest-worker-scan-latency / OPS-1003)

## What changed

`scripts/ada/nest-worker.py` — queue discovery is now O(1) rclone calls
(2 calls) instead of ~2 + N_pack + N_claim + N_pending:

- `pack_inventory()` now issues one `lsf <remote>/packs --recursive
  --format pt` — entry names AND modtimes in the same listing. Verified
  `lsf -F t` reports the identical local-time modtime `lsl` did, so
  stale-claim detection rides the inventory (per-claim `lsl` calls gone).
- New `fetch_pack_meta()`: one `copy --files-from` fetches every pending
  `pack.yml` + every `preflight.json`. `pack.yml` presence is known from
  the inventory, so missing-yml packs cost zero extra calls; per-pack
  `cat` fallback only if the batch copy itself fails.
- New `plan_pass()`: static admission (done/failed markers, live claims,
  stale-claim detection, pack.yml parse, `needs` fit) in scan order.
- `requires` is re-evaluated per pack at claim time via new
  `refresh_requires()` (one lsf per required pack, bounded by #requires)
  — preserves drain-in-one-pass: a dependency finished earlier in the
  same pass (by us or another worker) still unblocks dependents.
- New `--scan-only` flag: read-only discovery report, never claims —
  the safe measurement mode for KK-Mac verification.
- Robustness: non-mapping `pack.yml` now reports "bad pack.yml — skip"
  instead of crashing the whole pass; empty/half-staged pack dirs still
  report "no pack.yml — skip".

Preserved unchanged: first-writer claim (rcat + settle + sorted-winner
check), stale-claim release, needs/admission gates, remote-side artifact
verification, done/failed markers, serial concurrency. `requires_unmet`
keeps its old `(spec, remote_root)` signature — the existing
`TestNestWorkerGate` matrix passes unmodified.

## Measured (live, gdrive:ada-nest-kk-llm, 78 packs)

| version | rclone calls | wall |
|---|---|---|
| pre-290358235 (per-pack lsf) | ~82 | 196.5s |
| 290358235 (recursive lsf + lsl/cat) | ~4 | 8.1s |
| this change | 2 | 6.8s |

Quiet-queue delta over 290358235 is small; the win scales with live
claims (each cost +1 lsl ≈2.5s) and pending pack.yml cats (≈2.5s each) —
the soak-time scenario the card was filed for.

## Regression fixture / benchmark

- `tests/fixtures/nest-worker-queue.json` — 16-pack semantic matrix
  (done, failed, live claim, stale claim, mixed claims, needs-unmet,
  requires chains incl. preflight verdicts, missing/scalar pack.yml,
  empty dir).
- `tests/ada/test_nest_worker_scan.py` — 6 tests: admission matrix,
  claim-time requires gate, drain-in-one-pass, discovery call bound
  (≤2 calls), 200-pack bench (≤2 calls, <5s; measured 28ms), fresh-claim
  retention. All green; `tests.colab.test_pack_preflight` 36/36 green.
- Live bench: `python3 tests/ada/test_nest_worker_scan.py --remote
  gdrive:ada-nest-kk-llm` or `nest-worker.py --remote <r> --scan-only`.

## Trail

- Job record: `docs/ssot/jobs/ada/2026-11-07-nest-worker-scan-latency.yml`
- Commit: `7d4f4381b` on `dispatch/20261107-120758-measure-and-optimize-scripts-a`
- Board comment posted to jevnest-worker-scan-latency.

## Safety / scope kept

No second worker started, LaunchAgent untouched, nothing deployed, no
push to remotes. All remote ops during measurement were read-only
listings/copies; `--scan-only` was used for the new-code live run (0
pending packs on the remote anyway — nothing was claimable).

## How to verify

```
python3 tests/ada/test_nest_worker_scan.py            # 6 tests
python3 -m unittest tests.colab.test_pack_preflight   # 36 tests
python3 scripts/ada/nest-worker.py \
    --remote gdrive:ada-nest-kk-llm --scan-only       # ~7s, 0 writes
```
