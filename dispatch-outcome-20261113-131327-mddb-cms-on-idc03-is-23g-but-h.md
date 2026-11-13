# mddb-cms compact via export/import — 2026-11-13

## Result: SUCCESS — 24G → 2.4G, zero data loss, all verifier goals pass

mddb-cms on idc03 (`~/.config/containers/mddb-cms/data`) was 24G holding only
8445 doc-langs across 19 collections — ~22G freelist/dead-page bloat.
Compacted via the proven export→fresh-db→reimport→swap path
(docs/kb/mddb-prune-compact.md, procedure B).

## What was done

1. **Preflight** — tonight's gz backup existed (`~/mddb-backups/mddb-cms-20261113-0313.db.gz`,
   4.4G, ~10h old — past the 6h note but rollback was doubly covered by the
   `.pre-compact` file kept in-dir). No gzip running; instance healthy.
2. **Scratch** — fresh `localhost/mddb:2.15.4-lsn` on :11088 (`/tmp/cms-fresh`),
   same env as cms including ollama embedding (`127.0.0.1:11435`,
   gemini-embedding-2, 768d) on `--network=host`, plus
   `MDDB_EMBEDDING_QUEUE_SIZE=40000` — the fix for the ops-run slowness:
   default 4000-queue + 30s wait throttles /v1/add to embed-drain rate.
3. **Export** — all 19 collections → `/tmp/cms-compact/pass1/*.jsonl` (8445 doc-langs).
4. **Import** — `/v1/add` per doc; converged via two delta passes
   (`/tmp/cms-compact/delta.py`) keyed on **(key,lang)** — `/v1/export` emits
   one line per language variant and a key-only diff silently loses Thai
   variants.
5. **Freeze** — stopped all cms-writing timers on idc03 (26 units incl.
   media-inbox, cam-wall, kanban-commit, report generators), tony-dell
   (cms-h3-publish, flood-alert, chaba-cms-reflect), tony-omen (cam-wall-cms*),
   con01 (ada-flood-news, doc-mirror, jev-bench); held board-api's remote-write
   serialization via `flock /tmp/board-api-wp.lock`.
6. **Parity** — full semantic diff (key+lang+contentMd+meta) live↔scratch:
   ALL 19 collections identical after one 69-doc resync of churned pages.
7. **Swap** — stop mddb-cms, `podman unshare` swap, start; healthy in ~4s.
   `mddb.db.pre-compact` (24G) kept in-dir as rollback until tonight's backup.
8. **Stragglers** — old db mounted on :11089 and diffed vs live: **0 missed
   writes** (freeze held).
9. **Unfreeze** — all timers restarted; wp.lock released.
10. **Vectors** — embed queue is volatile (not persisted), so most docs
    arrived unembedded. `scripts/mddb/vector-reindex.py` is running against
    :11027 in background to re-embed ~30k chunks (content-hash skip makes it
    incremental). FTS `/v1/search` works fully already.

## Verification (card's stated goals)

- `curl -sf http://100.102.134.91:11027/v1/health` → 200 ✓
- Post-swap doc counts == export counts (8445, per-collection exact) ✓
- `du -sh mddb.db` = **2.4G** < 4G ✓
- `/v1/search` on infrastructure-ssot → hits; ada-cms-pages + chaba-lessons
  also return hits ✓

## Left behind / follow-ups

- `mddb.db.pre-compact` (24G) remains in the data dir — delete after
  tonight's backup: `podman unshare rm ~/.config/containers/mddb-cms/data/mddb.db.pre-compact`
- `/tmp/cms-compact/` on idc03 holds exports, scripts, logs (audit trail, ~40M)
- `vector-reindex.py` still running (nohup, pid on idc03); writes an ops-event
  doc to `ada-ha-events-tony` on the cms plane when done
- Runbook: `docs/ssot/jobs/cms/2026-11-13-mddb-cms-compact-export-import.yml`
  — includes reusable notes for the sibling card `mddb-leader-compact-export-import`

## How to verify

```
ssh idc03 'curl -s http://100.102.134.91:11027/v1/health'
ssh idc03 'du -sh ~/.config/containers/mddb-cms/data/mddb.db'   # ~2.4G
ssh idc03 'curl -s http://100.102.134.91:11027/v1/stats'        # total 8445
```
