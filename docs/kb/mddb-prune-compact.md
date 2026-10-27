# MDDB prune / distill / compact — standard procedure

Established 2026-10-26 (MEM-0871) after the ops-bank 18.9G→321M + main-bank 8.8G→3.3G
reduction. This is the reference for any "mddb is too big" work.

## The storage model — know which layer you're cutting

1. **Live documents** — what `/v1/search` returns. Cut by delete/delete-batch/delete-collection/truncate.
2. **Revisions** — every write keeps N revs per doc (unbounded without `maxRevisions`). Cut logically by `/v1/truncate`; prevented by collection-config `maxRevisions`.
3. **Vectors + index** — per-doc embedding chunks; rebuilt only via the embed queue (async).
4. **bbolt freelist** — deleted pages are marked free and REUSED, but the file never shrinks.
   Reclaim requires a physical rebuild (paths B or C below).
5. **Freelist-on-disk** — `MDDB_FREELIST_SYNC=true` persists the freelist on commit.
   Without it every open re-walks every page (the 45-min restart bug).

## Guard stack (keep it armed, always)

- `prune-old-docs.timer` on idc03 — daily 09:30, `scripts/ada/prune-old-docs.py`.
  Policy: ops `host-logs` >14d (`ts`), `ada-ha-events-*`/`ada-ha-snapshots-*` >30d.
  OPS_COLLECTIONS routes host-logs to `MDDB_OPS_URL`; everything else hits the leader :11023.
- `maxRevisions` per collection (`PUT /v1/collection-config`) — ops 3/10/5, cms 5, embed 3, main 20.
- `mddb-restart.timer` Sun 05:00 — all 5 containers (bounds RSS; restarts are seconds now).
- `MDDB_FREELIST_SYNC=true` on every quadlet.

## Procedure A — retention sweep (logical prune)

Run on idc03: `python3 scripts/ada/prune-old-docs.py [--dry-run]`

- Pages collections 5k at a time, delete-batches expired keys.
- Limit: on very large collections (~250k+ docs) `/v1/search` paging hits the server's ~50s
  request deadline — enumeration fails entirely (see path B escape hatch).
- For a collection that is entirely garbage (e.g. unbounded telemetry), prefer
  `POST /v1/delete-collection {"collection": "<name>"}` — one call.
  WARNING: it deletes EVERY doc including policy-keepers; on a ~260k-doc collection it ran
  in a single tx that OOM-killed mddb-ops (2.5G peak) — the drop still committed.
  Run during low load; expect the service to restart.

## Procedure B — export → fresh-db rebuild (telemetry / no-vector banks only)

Drops vectors, so ONLY for banks with no embeddings (ops).

1. `POST /v1/export {"collection":"<c>"}` → JSONL (key/lang/meta/contentMd per line) per collection.
2. Fresh scratch mddbd on an empty dir (`-v /tmp/x:/app/data:U`, port 11088) — opens instantly.
3. Re-add via `POST /v1/add {collection,key,lang,contentMd,meta}` (~80/s).
4. Verify counts on scratch stats vs export.
5. `systemctl --user stop mddb-<bank>`; `podman unshare sh -c 'mv mddb.db mddb.db.pre && mv <fresh> mddb.db'`;
   start; verify health+stats+producer write path; delete `.pre`.
6. Window cost: docs written between export and swap are absent (producers' cursors keep moving; raw sources like journald persist anyway).

## Procedure C — offline bbolt compact (vector-safe, any bank)

The only path that shrinks the file while preserving EVERYTHING (docs, revs, vectors, index).
`/v1/backup` and `/v1/restore` are FILE-LEVEL copies — they do NOT compact (verified 2026-10-26).

```bash
systemctl --user stop mddb-<bank>
podman run --rm -v ~/.config/containers/mddb-<bank>/data:/work:U \
  docker.io/golang:1.23-bookworm bash -c \
  "go install go.etcd.io/bbolt/cmd/bbolt@v1.4.3 >/dev/null 2>&1; \
   /go/bin/bbolt compact -o /work/mddb-compact.db /work/mddb.db"
podman unshare sh -c "cd ~/.config/containers/mddb-<bank>/data && \
  mv mddb.db mddb.db.pre-compact && mv mddb-compact.db mddb.db"
systemctl --user start mddb-<bank>
# verify: /health, /v1/stats doc counts, a vector-search with real scores — then:
podman unshare rm ~/.config/containers/mddb-<bank>/data/mddb.db.pre-compact
```

- ~10-15 min for an 8.8G db on idc03's loaded SSD. Downtime = the whole sequence.
- Rollback: `.pre-compact` file stays until verified.
- bbolt@v1.4.3 because latest needs go>=1.25; the 1.23-bookworm image is already pulled on idc03.

## Distillation guidance

- Raw telemetry (host-logs) is a SEARCH INDEX, not an archive — journald keeps originals per host.
  Digests (`logs-report.py` chain) already capture the signal; distill before deleting only if
  you need >retention-window queryability of raw lines.
- Memory banks are the opposite: never distill ada-*-bank collections — the raw docs ARE the memory.

## Gotchas that cost us hours — read before improvising

- `/v1/stats` is unanswerable on big/loaded dbs (>5min). Use `/v1/vector-stats`, file sizes, dry-runs.
- `/v1/backup` writes to the container's `/app/backups/` = EPHEMERAL overlay layer; verify pass can
  take 2h on a big db and the result may be discarded if the client disconnects. `podman cp` files out.
- Files in data dirs are container-uid owned — every file op goes through `podman unshare`.
- A copied live `mddb.db` opens fine on a scratch instance (recovers to last committed tx) — useful
  for offline enumeration when the live API can't page a huge collection.
- "copied/written" ≠ "indexed" — `embedded_documents == total_documents` is the only done signal.
