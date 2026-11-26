# KK-Mac kk-llm worker — idle polling & retry-burst investigation

Card: `kk-mac-worker-idle-poll-efficiency` (OPS-1036 follow-up).
Date: 2026-11-23. All live reads were read-only: `rclone lsf/cat`
against `gdrive:ada-nest/kk-llm`, the MDDB `ada-nest-heartbeats`
collection, and repo code. The LaunchAgent, worker, and queue were not
touched; no new worker was started.

## What is actually live

`net.adanest.kk-llm-worker` (user `kkkakk`) runs
`scripts/devnest/kk_mac_lane_worker.py --remote gdrive:ada-nest/kk-llm
--host local --workdir ~/.cache/kk-llm-worker --max-packs 1` at
**StartInterval=60** — not the `nest-worker.py --once` + 15 s the card
spec describes (that was the pre-11-14 state; OPS-1036 applied 60 s and
the lane worker replaced the generic one 2026-11-14, commit
`5edec6c787`). The repo reference plist
`scripts/ops/net.adanest.kk-llm-worker.plist` matches the live
arguments.

**Stale installer found and fixed here:** the OPS-1036 installer on
`origin/fix/ops-1036` rendered a plist invoking `nest-worker.py --once`
against the *old* remote `gdrive:ada-nest-kk-llm` — never the live
payload. Cherry-picked `fb58de0be` into this branch and corrected
`render()`; it now emits a plist byte-identical to the live reference
(verified by diff).

## Measured costs (live, 2026-11-23 ~18:38 ICT)

| measurement | value |
|---|---|
| Queue | 167 packs: 155 done, 6 failed, 5 fallback-held, 0 pending, 0 claimed |
| Recursive `lsf packs --recursive` (the idle scan) | 27 HTTPS requests, **5.35 s** wall, 0.29 s CPU |
| `lsf packs --dirs-only` (the cheap probe) | 5 HTTPS requests, **2.2 s** wall |
| single `rclone cat` | ~6 s (Drive latency floor) |
| Empty pass total (estimate) | python+imports ~0.4 s + local gate ~0.3 s + scan 5.35 s ≈ **6 s/pass** |
| At 60 s cadence, fully idle day | ~1,440 passes ≈ **~39k HTTPS req, ~7 CPU-min, ~2.4 h wall/day** |
| Task-run latency | recent `done` markers ~8 s wall (small tasks; `load_duration` 3.8 s + `eval_duration` 0.7–20 s) |
| Ollama residency | heartbeat `ollama_ok=true` (ts ~2 min old); idle passes only hit `/api/version` — they do not load or keep a model resident; model reload (~3.8 s) happens per task regardless of poll rate |
| kk-mac host right now | load_1m 1.70, disk 55 GB free, tmux empty, uptime 6.3 h |

### The retry loop, observed live

5 packs currently sit in `fallback` holds, all written 18:14–18:23 ICT:

- 4 × `memory_pressure_abort:13.0-14.0%<50.0%` — the node is genuinely
  memory-pressured; the executor's pre-load memory guard (MEM-1043)
  aborts *after* the pack is already claimed and synced down.
- 1 × `invalid_output:fact:launchd` — the model wrote "Launched", the
  deterministic verifier requires the literal substring "launchd". A
  pack fault: it can only pass by luck.

Under the current policy every `fallback` marker holds 30 min, is then
auto-released, and retries unconditionally — **forever**. Each retry
costs a claim + pack sync-down + contract (admission snapshot + memory
sample) + sync-back + marker writes ≈ 2 min of real work. This is the
"repeated bursts" the card is about; it is happening right now.

## Design (implemented on this branch, **not deployed**)

Three independent mechanisms, all inside `kk_mac_lane_worker.py`; the
LaunchAgent needs no change.

### A. Idle schedule — cheap probe + computed wake (not a longer interval)

`<workdir>/idle.json` persists `{dirs, next_probe, next_scan,
unchanged, probe_err}`. Each 60 s tick:

1. `gate()` runs as today (local probes only, ~0.3 s) — quiet-hours,
   drain file, owner-busy semantics unchanged.
2. If `now < next_scan` and `now >= next_probe`: **one dirs-only
   probe** (5 reqs/2.2 s). Dir set unchanged → exit, probe interval
   stretches 60→120→240→300 s. Changed → full plan.
3. If `now >= next_scan`: full recursive plan directly — no probe.
   `next_scan` is computed each pass as `min(earliest fallback-hold
   expiry, earliest live-claim stale time, now + 900 s)` — the worker
   wakes exactly when a hold expires or a claim could go stale, and
   never goes more than 15 min without a real scan.
4. Probe errors → exponential backoff to 900 s.

Flags: `--no-idle-schedule` (rollback to plan-every-pass),
`--probe-max-s`, `--rescan-max-s`.

Trade-off vs alternatives: a longer `StartInterval` is a plist change
worse on both axes (cost only drops linearly while latency rises);
producer-side index files add coupling for no gain — the dirs-only
listing *is* the index. Marker-level edits inside existing dirs
(manual requeue by deleting `done`) are the only thing the probe
misses; the 15-min rescan bound covers them.

### B. Retry accounting + quarantine — `retries/<n>-<kind>` markers

Each fallback verdict now also writes `retries/<n>-<fault|cond>` (kind =
`fault` for `invalid_output|task_invalid|artifacts_missing` — pack's own
deterministic failure; `cond` for lane conditions). The count is visible
in the plain inventory listing — enforcing the policy costs zero extra
remote calls.

- Effective hold escalates per pack: 30, 30, 60, 120, 240 min cap
  (`effective_hold_min`) — a stuck pack stops hammering every window.
- Quarantine to terminal `failed` when `faults >= 2` **or**
  `total >= 6`, whether seen at plan time (`plan()` emits a
  `quarantine` list) or produced by this pass (`_record_fallback`).
  `failed` reads `quarantined:<why>`; `retries/` stays for audit.
- `done` purges `retries/`; human requeue (delete `failed`/`done`)
  keeps the history so an already-bad pack re-quarantines quickly.

### C. Local memory gate — deny before any remote call

When `--host local` and the snapshot is otherwise eligible, `gate()`
adds `kk_mac_memory.sample("local")` + `evaluate(phase="pre")`
(60 % preload floor / 50 % abort floor — the same thresholds the
contract enforces). The 13 %-free condition aborting 4 packs today
becomes a gate deny — zero claims, zero syncs, zero marker churn.
Sample failure stays silent (the contract still fails closed at run
time). `DEVNEST_KK_MAC_MEM_GATE=false` opts out.

### Invariants preserved

Serial `--max-packs 1` pacing, first-writer claims (+3 s settle, loser
cleanup), stale-claim release (now *scheduled* by `next_scan`, same
60-min threshold), quiet-hours/drain/env kill gates, heartbeat
admission, the executor's independent verifier, `done`/`failed`
marker semantics, and the owner-capacity floors are all unchanged —
verified by the same test file (45 tests, all passing, incl. 19 new).

## Before/after — identical queue fixture

`evals/kk-mac-lane/idle_schedule_bench.py` runs real `pass_once` ticks
against a local rclone fixture (same code path, real subprocesses;
"before" = worker loaded from the merge-base commit). Simulated time
(`now=` + mtime re-stamping) makes holds faithful. Results in
`evals/kk-mac-lane/out/idle-schedule-bench-20261123.json`:

| scenario | metric | before | after |
|---|---|---|---|
| quiet queue: 20 done + 5 fresh holds, 12 ticks | remote ops / idle ticks | 12 / 0 | **4 / 11** |
| fault loop: invalid_output forever, 130 ticks (~2.2 h) | contract runs / remote ops | 5 / 174 | **2 / 66** (quarantined at fault #2, then terminal) |
| cond loop: memory abort forever, 400 ticks (~6.7 h) | contract runs / remote ops | 14 / 525 | **4 / 177** (escalating holds; would cap at 6 by ~12 h) |

Drive-side translation for the quiet case: 27 reqs × 12 = 324 requests
vs 27 + 3×5 = **42 requests per 12-min window — an ~87 % cut**, rising
toward ~95 % as the probe stretches and the queue history grows (the
recursive listing grows with pack count; the probe does not).

## Rollout plan (for review — nothing applied)

1. Land this branch (worker + installer + tests). kk-mac's exec
   checkout picks it up via `chaba-repo-sync` (≤60 min) — no plist
   change is required; `idle.json` self-creates on first pass.
2. Verify on-metal: `launchctl print gui/<uid>/net.adanest.kk-llm-worker`
   (state/interval unchanged), then `tail worker.log` for
   `idle:`/`quarantined:` lines and `cat ~/.cache/kk-llm-worker/idle.json`.
3. Watch one natural cycle: the 5 live held packs should show
   escalation/quarantine (`retries/` markers appear; the
   `invalid_output` pack goes `failed` on its next fault).

### Rollback

- Instant: `install-kk-llm-worker.sh` renders the same plist; add
  `--no-idle-schedule` to `ProgramArguments` (or `bootout`/`bootstrap`
  the old copy) — full legacy behaviour restored, `idle.json` ignored.
- Code-level: revert the worker file; `retries/` markers are inert to
  the old worker (it doesn't read them; they sync harmlessly).
- The quarantine `failed` markers are standard terminal markers —
  deleting one requeues the pack exactly as today.

### Residual risks / follow-ups

- Worst-case pickup latency for work staged *inside an existing pack
  dir* (not a new dir): ≤ `rescan_max_s` (15 min). New-dir staging —
  the producer's normal path — is detected within ~1–5 min.
- `memory_pressure_abort` verdicts during sustained owner pressure now
  cost a gate deny per tick (~0.4 s, local only) instead of a full
  claim→sync cycle.
- Optional later: producer writes a `_wake` marker to make pickup
  sub-minute during long quiet stretches; not needed at current
  volumes.
