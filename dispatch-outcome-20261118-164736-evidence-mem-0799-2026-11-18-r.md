# Dispatch outcome — idc02 mddb follower replication lag/health divergence (MEM-0799 recheck)

Card: `idc02-mddb-follower-11023-replication-de-ee75be` · Repo: mddb-fork · Runner: tony-macbook · 2026-11-18

## Root cause — confirmed in code and reproduced live

`/v1/replication/status` used **two different lag definitions in three places**, racing on shared state:

1. **Leader view** (`replication_handlers.go`, `replication_server.go`): `lag_ms = (leader_current_lsn − follower_confirmed_lsn) × 10` — a scaled LSN *count*, not a time. Under-reports real lag whenever writes run below ~100 entries/s.
2. **Follower apply path** (`replication_client.go` replicate loop): `lagMs = now − entry.Timestamp` where `entry.Timestamp` is the leader's commit time (binlog.Append). Real commit→apply lag — the honest signal.
3. **Follower ack path** (`ackLoop`, every 10s): overwrote the *same* `lagMs` atomic with its own `(LeaderLsn − lsn) × 10`. So the follower self-report flickered between real and synthetic depending on which writer ran last; `healthy = lagMs ≤ 30s` could flap with it.

Not clock skew (idc02/idc03 clocks agree to ~1s), not a stalled stream (`last_recv_age_ms` ~200-500ms, `connected:true`, LSNs advancing — watchdog: "applying: catch-up, leave it"). idc02 is **genuinely ~minutes behind during write bursts**: leader burst ~90 LSN/s vs idc02 HDD-bound apply ~15-25 LSN/s. Its `healthy:false` is *truthful* — the synthetic leader-side estimate was the lie.

Live samples during session: follower `replication_lag_ms` 173s→254s→288s while leader showed the same position as `lag_ms` 50500→42470→4350 — ~6x divergence and disagreeing severity. Reproduced the card's exact signature (final sample: follower 287806ms vs leader "warning" 4350ms).

## Fix — implemented, tested, NOT deployed

mddb-fork branch **`fix/replication-lag-real-time` @ `04c7b9a2`** (base `upgrade/2.18.10` @ b759ba3e, same as deployed `localhost/mddb:2.18.10-merge`). Pushed into `idc02:~/CascadeProjects/mddb-fork` (local branch, **not** origin); patch also saved at `docs/ssot/jobs/infrastructure/2026-11-18-mddb-replication-lag-real-time.patch`.

One definition everywhere: **lag = wall-clock age of the follower's applied/acknowledged tip; 0 at the leader's head** (idle leaders no longer read as lag).

- `internal/binlog`: bounded LSN→commit-ts index (16384 slots), populated on append + backfilled by `recoverLSN`; `TimestampAt(lsn)` needs no file scan.
- Leader (HTTP `followers[]` + gRPC `ReplicationStatus`): `lag_ms = now − commit_ts(confirmed tip)`; pre-index positions report the index-floor age (truthful lower bound); `lag_lsn` exposes the raw gap.
- Follower: `lastAppliedCommitTs` per apply, `leaderHeadLSN` per ack; `LagMs()` computed on read (a stalled-behind follower's lag grows in real time); ack ×10 kept only as pre-first-apply fallback.
- Heartbeat send-timestamps measure `leader_clock_offset_ms` — lag is computed in leader time so host clock skew can't corrupt it, and skew becomes observable (the MEM-0799 hypothesis, now measurable).
- Thresholds unchanged (leader 1s warn / 30s unhealthy; follower maxLag 30s) — now in real ms both sides.

Verified: `go build ./...`, `go vet` clean; `go test ./internal/binlog` + replication/status tests pass (idc02 `golang:1.27.3-alpine`). New tests cover the index, restart backfill, at-head→0, real lag, clock-offset correction, LagLSN. Updated `TestReplicationStatus_FollowerLag` for real semantics. Full-suite `go test .` shows one failure, `TestVerifyDatabaseThatTimesOut` — **pre-existing**: it fails identically on the unmodified `upgrade/2.18.10` base (env timing on the contended host), unrelated to this change.

Consumer check: `scripts/mddb-follower-watchdog.py` keys on `confirmed_lsn`/`last_seen_at` (unaffected); `scripts/mddb-binlog-canary.py` flags `status != healthy` — becomes truthful.

## Remaining gate

The fix needs an image rebuild + rolling restart (leader idc03 first, then idc02/con01) — **production change, needs explicit approval**. Then verify: both endpoints report ~the same lag; `healthy:true` sustained when caught up.

Separately: idc02's *real* lag is a capacity issue (HDD apply vs write bursts), not a metrics issue — the metric fix makes it honest; whether to tune `maxLag`/alert persistence or speed up idc02's apply is a separate decision.

Docs: `docs/ssot/jobs/infrastructure/2026-11-18-mddb-replication-lag-metric.yml`; card comment posted with the same summary.
