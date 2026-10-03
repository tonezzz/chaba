# MDDB backup + binlog retention — findings & runbook (2026-10-03)

Disk-pressure follow-up on idc01 (94% → 62%) and tony-dell (99% → 79%).

## Findings

### `/v1/backup` corruption — FIXED upstream in v2.15.4

- Symptom: nightly backup files that crash `bbolt.Open` on restore with
  `freepages: failed to get all reachable pages (… needs to be < than key of
  the next element in ancestor …)`.
- Cause: HTTP/MCP backup copied the DB file while bbolt was writing — torn
  freelist. gRPC backup already used a read-tx.
- Fix: `services/mddbd/db_backup.go` — `backupTo()` writes via
  `tx.WriteTo` inside a read transaction and **verifies the copy opens**
  before renaming (upstream PR #281, in tag `v2.15.4`). A verify failure now
  means the *live* DB is damaged, not the copy.
- **Verified restorable 2026-10-03**: native backup taken on the running
  `localhost/mddb:2.15.4-allowlist` leader opened cleanly in a throwaway
  container (freelist rescan ≈ 2.5 min for a 3.4 GB DB) and served a real
  document.
- Running image must be ≥ 2.15.4 for this to hold. idc01 runs
  `localhost/mddb:2.15.4-allowlist` (built from `mddb-fork`,
  `feat/vector-algorithms`). Stock `docker.io/tradik/mddb:2.15.4` lacks the
  `MDDB_VECTOR_ALGORITHMS` allowlist the prod env sets.

### `mddb-backup.sh` (idc01 `~/mddb-backup.sh`, timer 02:30 nightly)

- Now: tier-1 **native `/v1/backup`** is primary again (consistent +
  server-verified); tier-2 `podman cp` filecopy + open-verify is fallback
  only, retried ×3 (the copy races live bbolt writes — that race is what
  produced `*.UNVERIFIED`).
- One ~3.4 GB file/night instead of two; retention keeps last 4 + last 2
  UNVERIFIED. Versioned at `stacks/idc01/mddb/mddb-backup.sh`.
- The in-container `/app/backups/` copy is removed after pulling out.

### Binlog (`mddb.binlog`) — retention existed but was never wired

- `BinlogConfig{MaxSize: 256MB, MaxAge: 24h}` was passed but never
  enforced; `Rotate(keepFromLSN)` existed with no caller. File grew
  ~1 GB/day → 9.2 GB.
- Patch on `mddb-fork` (`binlog-retention` → merged into
  `feat/vector-algorithms`, commit `598c57d`): `binlogJanitor` on the
  replication server rotates when the file exceeds `MaxSize`:
  - followers connected → keep from `min(ConfirmedLSN)` (a follower only
    loses entries it already applied; confirmed=0 followers are ignored,
    they need the snapshot stream anyway);
  - no followers → keep entries younger than `MaxAge` (a follower returning
    past the window is refused and re-syncs via snapshot — what `MaxAge`
    always implied).
- New env knobs: `MDDB_BINLOG_MAX_SIZE` (bytes, def 256MB),
  `MDDB_BINLOG_MAX_AGE` (def 24h), `MDDB_BINLOG_ROTATE_INTERVAL`
  (def 15m, 0 disables).
- Smoke-tested: 4KB cap + 3s age → rotation fired, file shrank, oldestLSN
  advanced, server stayed healthy.

## Upgrade runbook — `localhost/mddb:2.15.4-blrotate` on idc01

The image is built on tony-dell from `mddb-fork` `feat/vector-algorithms`
(now including the janitor). **Deploy = production mddb leader restart —
requires approval.** Expect the NoFreelistSync open-rescan downtime
(~2.5 min measured for a 3.4 GB DB on a fresh file; the live DB with its
hot freelist may differ — plan for a few minutes of mddb unavailability;
ada-pi/tools will error during it).

```bash
# 1. ship the image
ssh tony-dell 'podman save localhost/mddb:2.15.4-blrotate | \
  ssh idc01 podman load'

# 2. pin it
ssh idc01 'sed -i "s|^Image=.*|Image=localhost/mddb:2.15.4-blrotate|" \
  ~/.config/containers/systemd/mddb.container && \
  systemctl --user daemon-reload'

# 3. optional tuning (add to [X-Container] Environment= lines):
#    MDDB_BINLOG_MAX_SIZE=268435456  (default already 256MB)
#    MDDB_BINLOG_ROTATE_INTERVAL=15m (default)

# 4. restart — mddb DOWN for the open-rescan window
ssh idc01 'systemctl --user restart mddb'

# 5. verify
ssh idc01 'podman logs mddb | grep -iE "janitor|binlog enabled";
  curl -s http://100.74.146.0:11023/v1/replication/status;
  ls -la ~/.config/containers/mddb/data/mddb.binlog'
```

Watch for `binlog retention janitor started` at boot, then `rotating
binlog` once the file exceeds MaxSize. On first start it will have the
full ~9 GB history until the first rotation — that's expected.

Rollback: point `Image=` back at `localhost/mddb:2.15.4-allowlist` and
restart.

## Follower note

tony-dell's follower already sends `AcknowledgeLSN` every 10s
(`replication_client.go ackLoop`) — no follower change needed.

## Backup state after 2026-10-03 cleanup

- idc01 `~/mddb-backups/`: `mddb-20261003-1755.db` (native, verified),
  `mddb-filecopy-20261003-1752.db` (verified), `mddb-filecopy-20261002-0230.db`.
- tony-dell `~/.local/share/mddb-backups/`: `mddb-20260928-0230.db` +
  `filecopy/mddb-filecopy-mddb-20261002-0230.db` retained; older gens removed.
- tony-dell freed ~23G (old backup copies, ubuntu ISO, build caches);
  idc01 freed ~32G (stale incident artifacts + old backups).
