# dispatch-outcome — kk-mac-worker-idle-poll-efficiency

## Result

Investigated the live kk-llm lane worker **read-only** (rclone + MDDB
heartbeat; no SSH needed, no LaunchAgent/worker/queue changes), designed
the idle + retry policy, implemented it on this branch with tests and an
identical-fixture A/B bench, and produced a rollout/rollback plan for
review. Report: `docs/kb/kk-mac-worker-idle-schedule.md`.

## What changed

- `scripts/devnest/kk_mac_lane_worker.py` — (a) idle schedule:
  `<workdir>/idle.json` + dirs-only probe (5 HTTPS reqs vs 27 for the
  recursive scan) + computed `next_scan` wake times (hold expiries,
  claim staleness, 15-min rescan bound) + probe-error backoff;
  `--no-idle-schedule` is the rollback flag. (b) `retries/<n>-<kind>`
  markers, escalating holds (30→240 min), quarantine to `failed` at
  2 faults or 6 total retries. (c) local memory gate: deny before any
  remote call when free mem is below the preload floor
  (`DEVNEST_KK_MAC_MEM_GATE=false` opts out).
- `scripts/ops/install-kk-llm-worker.sh` + test — cherry-picked
  `fb58de0be` (unmerged OPS-1036 work) and fixed its rendered plist,
  which pointed at `nest-worker.py` + the old `gdrive:ada-nest-kk-llm`
  remote. Now renders byte-identical to the live lane-worker plist.
- `tests/devnest/test_kk_mac_lane_worker.py` — 19 new tests (45 total,
  all pass).
- `evals/kk-mac-lane/idle_schedule_bench.py` + `out/idle-schedule-bench-
  20261123.json` — reproducible before/after fixture bench.
- `docs/kb/kk-mac-worker-idle-schedule.md` — full investigation,
  measurements, design, rollout + rollback.

## Live findings

- Live worker is `kk_mac_lane_worker.py` at StartInterval=**60**
  (card's "15 s nest-worker.py" predates the 11-14 lane cutover).
- Queue: 167 packs — 155 done / 6 failed / 5 fallback-held / 0 pending.
- Retry burst in progress: 4 packs cycling on
  `memory_pressure_abort:13%<50%` + 1 pack on deterministic
  `invalid_output:fact:launchd` — each retried every flat 30-min hold,
  forever.
- Empty pass ≈ 27 HTTPS reqs / 5.35 s / 0.29 s CPU every 60 s
  (~39k reqs + ~7 CPU-min per idle day). Task-run latency ~8 s.
- kk-mac heartbeat healthy (ollama_ok, load 1.70, disk 55 GB).

## Bench (identical fixture, real rclone subprocesses)

| scenario | before | after |
|---|---|---|
| quiet queue, 12 ticks | 12 remote ops, 0 idle ticks | 4 ops, 11 idle |
| invalid_output loop, 130 ticks | 5 runs / 174 ops | 2 runs / 66 ops — quarantined |
| memory-abort loop, 400 ticks | 14 runs / 525 ops | 4 runs / 177 ops — escalating holds |

## Verify

- `python3 -m unittest tests.devnest.test_kk_mac_lane_worker
  tests.ops.test_kk_mac_worker_installer` → 45 tests OK.
- `python3 evals/kk-mac-lane/idle_schedule_bench.py` reproduces the A/B.
- Deploy path (post-review): merge → kk-mac exec checkout syncs via
  chaba-repo-sync; no plist change needed; confirm with `tail
  ~/.cache/kk-llm-worker/worker.log` for `idle:`/`quarantined:` lines.

lessons:
- rclone's local backend accepts plain paths for every op the worker
  uses (lsf/rcat/cat/copy/deletefile) — a /tmp fixture is a faithful
  remote for A/B testing queue workers without Drive.
- Simulated-time benches must re-stamp written markers' mtimes to the
  sim clock (bounded to the real pass window) or holds look instantly
  stale.
- The ops-1036 installer cherry-picked onto master rendered a STALE
  payload (generic nest-worker + old remote) — verify rendered plists
  against the live LaunchAgent args, not just plist syntax.
- kk-mac lane worker ≠ nest-worker.py: `net.adanest.kk-llm-worker`
  runs kk_mac_lane_worker.py on gdrive:ada-nest/kk-llm; card text said
  15 s but live is 60 s — verify live state before trusting the spec.
- tony-macbook has no ssh path to kk-mac; the queue (rclone gdrive:)
  and MDDB ada-nest-heartbeats are the live read surfaces.
