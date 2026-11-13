# Dispatch outcome — mddb-leader-compact-export-import

**Result: DONE — all five card verifier goals pass.**

## What was done

Compacted the idc03 mddb **leader** (`~/.config/containers/mddb/data/mddb.db`)
from **12.62G → 3.65G (3.46x)** using offline `bbolt compact` (Procedure C in
`docs/kb/mddb-prune-compact.md`) rather than the card's literal export/import
spec. The deviation was raised as a board request with bbolt marked
recommended; no answer arrived and the marked default was followed. Reasons:
preserves revisions + vectors + FTS (no multi-hour reindex), keeps the binlog
(followers don't need re-seed), zero data-loss window, and the tool is
non-destructive (rollback = delete output + restart).

Sequence: fresh native backup → zero-risk trial of `bbolt check`+`compact` on
the previous night's backup (passed; opened healthy in a scratch mddbd with
vectors intact) → `systemctl --user stop mddb` 13:47:52 → compact 7m14s →
`podman unshare` swap → start 13:55:07. **Leader downtime: 7m15s.**

## Verification

- `/v1/health` → 200, durable, wr (all three instances verified)
- Doc counts: 20,388 vs 20,376 pre-run; every delta is a post-snapshot live
  write (device-telemetry, events, scenario reports, probe docs)
- Size: 3.65G (goal <9G)
- `/v1/vector-search` returns real scored results — index survived compact
- idc02 follower: caught up to exact head LSN, healthy, probe replicated
- con01 follower: was **5.5 days behind pre-existing** → re-seeded via native
  leader backup file (md5-verified); mddb auto-triggered "replication LSN too
  old → full snapshot" resync; now confirmed at exact head LSN 250,770,195,
  healthy

## Notes / lessons

- **LSN rewind**: post-swap the leader's commit marker restarted ~49k LSN
  below the pre-stop binlog tail; appends resume from there. Writes committed
  in the first ~90s after restart can be dedup-skipped by already-caught-up
  followers — only a synthetic probe doc was affected (no production writes
  could land while the leader was stopped).
- **Mistake made + fixed**: first con01 seed attempt scp'd a file that was
  still hardlinked into a live scratch mddbd — torn pages, follower panic
  loop. Restored con01's old file (stale-but-serving), then re-seeded with a
  server-verified native backup + md5 check. Rule: never ship a db file an
  mddbd has open.
- golang:1.23-bookworm was no longer on idc03; bbolt@v1.4.3 was staged in a
  mounted gopath for the downtime window.
- A parallel dispatch was running the mddb-cms compaction on the same box —
  no collision (different data dirs), only shared I/O.
- Followers idc02 (7.1G) and con01's old file (8.8G) carry the same dead-page
  bloat — same procedure applies if ever needed (con01 already re-seeded
  compact).

## Artifacts / rollback kept

- `idc03:~/mddb-backups/mddb-20261113-1319.db.gz` (pre, 2.6G) +
  `mddb-compacted-20261113-1417.db.gz` (post, 1.57G)
- `idc03:~/.config/containers/mddb/data/mddb.db.pre-compact-20261113` (12.6G)
- `con01:~/.config/containers/mddb-follower/data/mddb.db.pre-reseed2-20261113` (8.8G)
- Delete rollback files after soak. Scratch `/tmp/leader-compact/` cleaned.
- Trail: `docs/ssot/jobs/mddb/2026-11-13-leader-compact-bbolt.yml`

## How to verify

```
ssh idc03 'curl -s http://100.102.134.91:11023/v1/health; \
  du -sh ~/.config/containers/mddb/data/mddb.db; \
  curl -s http://100.102.134.91:11023/v1/replication/status'
```
All followers should show `confirmed_lsn` at/near `current_lsn`, status healthy.
