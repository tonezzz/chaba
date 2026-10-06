# Dispatch outcome — mddb-embed-queue-recovery

## What was done

**1. Enumerated the dropped docs.** Pulled `journalctl --user -u mddb.service`
on idc01 (the leader at the time; mddb is masked there now). The drop window was
**2026-10-04 20:47 → 2026-10-05 11:50 +07** — wider than the card's
"11:40-11:55 UTC" note: 3,160 "embedding queue full, dropping job" events
covering **1,320 unique docIDs** (some docs dropped repeatedly as revisions were
written). Top collections: ada-ha-bank-devin-tony (677 unique), infrastructure-ssot
(143), ada-cms-pages (127), ada-ha-bank-general (91). Full docID list committed at
`docs/ssot/jobs/infrastructure/2026-10-06-mddb-embed-queue-dropped-docids.txt`;
per-doc detail JSON in `reports/mddb-embed-queue/` (gitignored). idc03 journal
post-migration: zero drops.

**2. Reindex — coverage verified, not just assumed.** `/v1/vector-reindex` skips
docs whose stored vector content-hash matches, so a sweep is authoritative.
Swept every collection except host-logs on idc03: **embedded=15, skipped=12,259,
failed=0**. Every 10-04/05 dropped doc already had a vector (the 10-05 22:15
sweep did the backfill). host-logs was deferred deliberately — its ~2,000-doc
"gap" is embed jobs already in the queue (which sat saturated at 4000/4000 most
of the session from hourly per-host log-shipper bursts of ~2,000 docs each);
inline-reindexing would double-embed and hammer the OpenRouter proxy.
`dropped=0` on idc03 the whole time — no enqueue losses.
Gotcha found: `/v1/vector-stats` `embedded_documents < total_documents` does NOT
mean missing vectors — it's in-memory index residency; the reindex skip count is
the coverage truth.

**3. Saturation tripwire — live.** `scripts/ada/embed-probe.py` gained
`check_queue()`: each 15-min tick reads `/v1/vector-stats` `queue{depth,dropped,size}`
and emits ada-ops events to ada-ha-events-tony — `embed_queue_saturated` on the
rising edge past warn (depth≥500) / crit (≥3000), `embed_queue_drops` when
droppedTotal grows (rate-limited 30min), `embed_queue_drained` on recovery.
Thresholds env-tunable (`EMBED_QUEUE_WARN_DEPTH`/`_CRIT_DEPTH`/`_DROP_ALERT_MIN_S`).
State in `~/.local/share/ada/embed-queue.state`. Also added the two new event
types to `scripts/ops-digest.py` FLAGGED so they surface in the nightly digest.
Verified live: real `embed_queue_saturated` events written while the queue sat
at 3978/4000.

## Fixed en route

`mddb-vector-reindex.service.d/endpoint.conf` on idc03 pointed at
`http://127.0.0.1:11023`, but mddb binds only the tailnet IP — the unit could
never have run post-migration. Updated to `http://100.102.134.91:11023` and
daemon-reloaded. (The same stale dropin probably exists on idc01; its mddb is
masked so it's moot, but worth fixing if it's ever revived.)

## Changed files (committed on dispatch branch d8a5af30)

- `scripts/ada/embed-probe.py` — queue tripwire
- `scripts/ops-digest.py` — FLAGGED += embed_queue_saturated/embed_queue_drops
- `docs/ssot/infrastructure/ssot.services.yml` — mddb related_units +
  tripwire pointer
- `docs/ssot/jobs/infrastructure/2026-10-06-mddb-embed-queue-recovery.yml` —
  trail doc (enumeration numbers, coverage notes, decisions, verify commands)
- `docs/ssot/jobs/infrastructure/2026-10-06-mddb-embed-queue-dropped-docids.txt` —
  the 1,320 dropped docIDs

## How to verify

```bash
curl -s http://100.102.134.91:11023/v1/vector-stats | jq .queue
# ops events:
curl -s -X POST http://100.102.134.91:11023/v1/search -H 'content-type: application/json' \
  -d '{"collection":"ada-ha-events-tony","filterMeta":{"kind":["ops-event"]},"limit":100}' \
  | grep embed_queue
# after merge + idc03 pulls ~/CascadeProjects/chaba:
journalctl --user -u mddb-embed-probe.service --since -1h   # "queue depth=N/4000 dropped=M" lines
```

## Caveats / follow-ups

- The tripwire code goes live when idc03's `~/CascadeProjects/chaba` checkout
  pulls master (it tracks origin; the unit file itself is unchanged).
- `mddb-embed-probe`/`ops-health-report` units on idc03 are hand-installed, not
  registry-rendered — noted in the trail doc; did not convert to avoid fighting
  the live units.
- Queue saturation by log-shipper bursts is now routine (depth hit 4000 twice
  this session, dropped=0). If drops do start recurring, the systemic fix is a
  dedicated mddb-ops instance for host-logs (already noted in ssot.jobs.yml) or
  disabling embeddings on host-logs.
