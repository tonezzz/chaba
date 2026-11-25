# Dispatch outcome — mddb-ops-regrowth-watch (2026-11-25)

## Verdict

The 6.2G -> 8.1G regrowth in ~23h is **not** a freelist/FREELIST_SYNC
problem. Measured on a copy of the live DB with bbolt v1.4.3:
`FreePageN=1614` (~6.6 MiB, 0.08% of the 8.1G file); the file is ~all
live b+tree data. FREELIST_SYNC is a restart-latency knob, not a
capacity knob — it is set correctly on the mddb-ops quadlet.

The real driver: **host-logs retention has been silently broken since
~Nov 23**. `prune-old-docs.service` (daily 09:30 on idc03) fails every
run at `host-logs: list failed` — the script paged the entire
collection unfiltered and filtered `ts` client-side; at ~660k docs the
search exceeds the server's ~30-50s write deadline, so it deletes 0
docs. host-logs is at 640,819 docs (~45k/day ingest, 3d retention
should hold ~135k). Same failure class as MEM-0871 — the collection
regrew past the paging limit while the sweeper was broken.

Secondary bug: `/v1/search` caps pages at 1000 docs regardless of the
requested limit, so `PAGE_SIZE=5000` + `len(page) < PAGE_SIZE: break`
would have exited after page 1 even without the timeout.

## What changed (commit 4b51121a2e7 on dispatch branch)

- `scripts/ada/prune-old-docs.py` — `/v1/search` now sends
  `"filter": {ts_key: {"lt": cutoff}}` (verified server-side operator
  filter via meta indices; `filter_meta` does NOT do operators),
  `PAGE_SIZE` 5000->1000, list phase retries 4x with backoff for
  load-induced write timeouts.
- `docs/ssot/jobs/mddb/2026-11-25-ops-regrowth-watch.yml` — full trail.

## Actions taken on idc03

- Copied live mddb.db to /tmp for the freelist measurement (left at
  /tmp/ops-stats/mddb.db, 8.1G — safe to delete).
- Deleted one manual 1000-doc batch while verifying the loop.
- Launched catch-up prune: `nice -n 10 python3 -u
  /tmp/prune-old-docs.py --only host-logs` (PID was 2193157, log
  /tmp/prune-host-logs.log). Deletes all host-logs older than 3d
  (~520k docs; ~12k removed in first ~15min => est. ~8-11h). This is
  the standing daily policy executing late — journald keeps originals.
  Progress check: host-logs totalDocs 659,565 -> 647,419 and falling.

## Answers to the card

- Delete-rewrite vs FREELIST_SYNC: no — freelist is 0.08% of file.
- telemetry-prune retention vs periodic compaction: retention is the
  right lever and was already the plan; it was broken. After the
  catch-up drains to ~135k docs (~1.5-2.5G live), one Procedure-C
  bbolt compact can still reclaim the high-water file size if wanted.

## How to verify

- `ssh idc03 'cat /tmp/prune-host-logs.log'` — one summary line at end.
- `curl -s http://idc03.taila0626a.ts.net:11026/v1/stats` — watch
  host-logs documentCount fall toward ~135k; file size lags until a
  compact (file won't shrink on deletes).
- Tomorrow 09:30 `prune-old-docs.service` should succeed once the
  patched script reaches the exec checkout via chaba-repo-sync.

lessons:
- /v1/search caps pages at 1000 docs regardless of requested limit — PAGE_SIZE=5000 silently truncated sweeps.
- /v1/search `filter` (operators) works server-side; `filter_meta` is exact-match only — wrong param name = silently unfiltered results.
- mddb delete_where/update_where are MCP-surface only; REST /v1/delete-where is not routed on 2.18.10 and ops instances run MDDB_MCP_ENABLED=false.
- bbolt db.Stats() reports zeros on ReadOnly open — freelist only populates on a normal open of a (copy of the) file.
- prune-old-docs failed silently for ~12 days because the unit only logs per-sweep summary lines; a stuck sweep looks identical to a healthy one in `systemctl status` until it exits 1.
