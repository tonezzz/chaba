# mddb — leader on idc03, follower on idc02 (and formerly tony-dell)

Document database backing Ada memory, CMS pages, and SSOT sync.

## Files

- `mddb.container` — leader quadlet. Secrets externalized to
  `~/.config/secrets/mddb.env` (`MDDB_MCP_API_KEYS`, `MDDB_REPLICATION_SECRET`).
- `mddb-backup.sh` — backup script (native `/v1/backup` primary on 2.15.4+,
  filecopy fallback with verification retries).

## Ports (tailnet)

- `11023` HTTP/REST · `11024` gRPC replication · `9000` MCP

## State

- `~/.config/containers/mddb/data/` — mddb.db + mddb.binlog
- `~/.config/containers/mddb/vaults/` — vault files
- `~/mddb-backups/` — backup generations (script-managed retention)

## Image

`localhost/mddb:2.15.4-allowlist` — built from `~/CascadeProjects/mddb-fork`
branch `binlog-retention` (4 commits: retention janitor, streaming Rotate,
snapshot-below-oldest incl. LSN 0, Recv-side FailedPrecondition→snapshot).
Build host: idc02 (Dockerfile builds in-container; no host Go needed).
Ship to another host: `podman image scp localhost/mddb:<tag> <host>::`.

## Move runbook (idc03 → anywhere)

Do NOT rsync mddb.db — replicate it:

1. On the target host, run the quadlet as follower:
   `MDDB_REPLICATION_ROLE=follower`, `MDDB_MODE=ro`,
   `MDDB_REPLICATION_LEADER_ADDR=<leader>:11024`, `MDDB_NODE_ID=<host>`.
2. Wait for snapshot pull + converge (`/v1/replication/status` on leader —
   `confirmed_lsn` catches up to `current_lsn`, lag → 0).
   Large DBs on slow disks need `MDDB_VERIFY_TIMEOUT=6h` (snapshot verify
   does a full bbolt page walk; on a loaded HDD it exceeds the 1h default).
3. Stop the old leader, start the target in `role=leader mode=wr` with
   `MDDB_NODE_ID=<host>` and the old leader's ports.
4. Repoint remaining followers' `MDDB_REPLICATION_LEADER_ADDR` and restart.
5. Rollback = reverse step 3/4.

Never run two leaders. The follower keeps a `.pre-snapshot` db + a
`.snapshot.tmp` during pulls — clean up after convergence.
