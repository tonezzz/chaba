# Dispatch outcome — mddb-follower-lsn-persist

Card: `mddb-follower-lsn-persist` · Session: dispatch-wt-20261006-103003 · Repo: `~/CascadeProjects/mddb-fork` (worktree `~/CascadeProjects/mddb-wt-lsn-persist`, branch `follower-lsn-persist`)

## What changed

The follower's `lastAppliedLSN` used to live only in memory — every restart
reported `fromLSN=0`, tripped the leader's below-oldest check, and re-pulled
the full snapshot (observed live on idc02: 4.27 GB on 2026-10-05, 6.1 GB on
2026-10-06). The applied LSN is now persisted at
`_mddb_replication / last_applied_lsn` **inside the replicated BoltDB**,
written in the same transaction as the applied entries — atomic with the
data, no extra commit/fsync, and it can never run ahead of the file the way
a sidecar can after a manual database swap.

Commits on `follower-lsn-persist` (rebased onto `feat/vector-algorithms` @ d77c6ae):

- `e1192e2` feat(replication): persist follower applied LSN across restarts
  - `replication_applier.go` — marker bucket/key, `putAppliedLSN` at the tail
    of every `Apply`/`ApplyBatch` tx; `NewReplicationApplier` loads it;
    `PersistLSN` (out-of-tx write), `ReloadPersistedLSN` (post-restore).
  - `replication_client.go` — `requestSnapshot` persists the snapshot LSN
    after the swap (the incoming leader copy carries no marker).
  - `restore_backup.go` — manual restores on a follower reload the marker so
    the stream resumes from the restored file's position.
- `8a16d20` build(mddbd): fully-qualify Dockerfile base images — idc02's
  podman has no unqualified-search registries; short-name FROM failed.
- `cb65896` docs(dispatch): decision record → `reports/2026-10-06-follower-lsn-persist.md`

9 new applier tests (write/reload/reopen/batch/checkpoint/isolation).

## Important course correction

Work initially branched off `binlog-retention` (0b46e57), which does **not**
contain the snapshot-loop fixes merged into `feat/vector-algorithms`
(d77c6ae: freelist-in-snapshot, `verifySnapshot` open-proof, progress
logging, stream-test fix). An image built on the wrong base was briefly
deployed to idc02 — caught because its verify child took the abandoned
slow full-check path on the 6.1 GB snapshot. Branch was rebased, image
rebuilt and re-shipped. **Build mddb deploys only off
`feat/vector-algorithms`.**

## Deployment (image tag `localhost/mddb:2.15.4-lsn`, `3c22910c755f`)

- Built on idc02 via the Dockerfile from rsynced context `~/mddb-build-lsn/`.
- **idc02 (follower)**: quadlet `Image=` pinned, restarted — verified live.
- **idc03 (leader)**: image loaded via `tony-omen` ssh hop (idc03 does not
  accept tony-dell's key; tony-omen uses `~/.ssh/id_idc03`), quadlet pinned —
  **NOT restarted**: leader restart = production outage, approval requested
  on the board (`idc03-leader-restart-needed-to-pick-up-m-2cf496`).
- `stacks/idc03/mddb/mddb.container` in chaba updated to match (committed on
  the dispatch branch).

## Result / verification

- `go build ./...`, `go vet`, `gofmt` clean; **full suite `go test -count=1 .`
  passes in 91 s** on the correct base (the earlier 15-min timeout was the
  pre-existing broken stream tests on binlog-retention, fixed upstream by
  ad7708a).
- Live proof on idc02: first restart on the new image re-snapshotted once
  (no marker existed yet — 6.45 GB, verify ~8.6 min open-proof + ~8.6 min
  reopen walk); after `snapshot applied`, a second restart logged
  **`replication applier resuming from persisted LSN","lsn":148280580`** and
  streamed — no snapshot. `/v1/replication/status` reports
  `current_lsn` advancing (148.29M+); follower is replaying the ~1.2M-LSN
  backlog accrued while it was down (`healthy:false` until caught up —
  leader shows it `unhealthy` at `lag_ms`~1.2M, draining via the binlog
  tail; entries retained, oldest 146.99M < follower position).

## Open items

- **idc03 leader restart** — pending operator approval (board request).
- **Merge `follower-lsn-persist` → `feat/vector-algorithms`** — flagged in
  the same request; a future rebuild off `feat/vector-algorithms` would lose
  the fix until merged.
- Follower lag will show `unhealthy` until the write-burst backlog drains —
  expected, not a defect of this change.
- idc02 `~/mddb-build-lsn/` build context left in place for future builds.
