# dispatch-outcome — fix-mddb-stats-timeout-overnight

## Track A — the perf bug is real (root cause found)

`GET /v1/stats` on the idc03 primary (`handleStats`, `services/mddbd/http_handlers_meta.go:399`
in the mddb fork `~/CascadeProjects/mddb`) cursor-walks **every key** in three bbolt buckets:

| bucket   | keys (backup 2026-10-13 02:30) | leaf bytes |
|----------|-------------------------------|------------|
| docs     | 153,396                        | ~104 MB    |
| rev      | 626,388                        | ~2.0 GB    |
| idxmeta  | 825,528                        | ~86 MB     |

…with `strings.Split(string(k))` per key inside one read tx, **then** calls
`collectionChecksum()` per collection — 57 more read transactions that each
prefix-walk that collection's docs with crc32 over key+value-head.

Measured on live :11023 (2026-10-13): `/v1/stats` took **0.95s / 16.3s / 28.6s /
>60s** across four calls — variance tracks page-cache warmth and write
contention. `/metrics` (600ms) and `/v1/vector-stats` (430ms) are fast when the
server is idle.

The Oct-10 incident reproduced live in my verification run: **while a `/v1/stats`
walk was in flight (16.3s), the concurrent `/metrics` and `/v1/vector-stats`
probes timed out at 5s** — the stats walk starves sibling requests of CPU/IO
(readers don't block each other at bbolt level; `DBView` is a shared RLock).
That window also had ~1.6GB binlog rotations every ~15min, TTL cleanups, and
failing embed retries (ollama proxy 502s). Not caused by the CMS split —
:11027 took chaba content, but :11023 still holds 149k docs/57 collections/8.1GB.

Side effect worth noting: every stats call pins a long-lived bbolt read tx, so
freed pages can't be reclaimed — it feeds the freelist/RSS growth that
`mddb-restart.timer` (weekly Sun 05:00) exists to bound.

**Root fix carded:** `mddb-stats-o1-counts` (MEM-0582, backlog) — mddb fork is
outside this repo; recommended maintained per-collection counters / response
cache (~60s) / async-or-dropped checksums.

## Track B — audit fix (implemented + verified)

- `scripts/audits/http-health-audit.mjs`: new per-service `severity: warn`
  support — probe failures (timeout, unreachable, wrong status, cert<7d)
  report as warns instead of issues; the 2x timeout retry is skipped for
  non-fatal services (a second walk just doubles DB load). If the same URL is
  declared in multiple health files, any declaration lacking `severity` keeps
  the probe fatal (conservative merge).
- `docs/ssot/infrastructure/ssot.health.home.datastore.yml` + `ssot.health.mobile.yml`
  (the three endpoints are declared in both): `severity: warn` added to
  `mddb-stats`, `mddb-vector-stats`, `mddb-metrics`, with notes explaining why.
  `mddb-api` /health stays fatal — that's the liveness probe.
- `docs/ssot/infrastructure/ssot.audit.yml`: http-health description updated.

## Verify

- `node scripts/audits/http-health-audit.mjs` → **rc=0, 80/80 ok** (mddb-stats
  951ms this run; mddb-* all green).
- Synthetic check: dead port + `severity: warn` → warn only, rc=0; same dead
  port without severity → issue, rc=1.
- Next overnight run on chaba-tony-dell should show health_snapshot rc=0 even
  if /v1/stats exceeds 60s (it will land as a visible warn, not a step failure).

## Files changed

- `scripts/audits/http-health-audit.mjs`
- `docs/ssot/infrastructure/ssot.health.home.datastore.yml`
- `docs/ssot/infrastructure/ssot.health.mobile.yml`
- `docs/ssot/infrastructure/ssot.audit.yml`
- `docs/ssot/jobs/infrastructure/2026-10-13-mddb-stats-timeout.yml` (trail)

Board: findings comment posted on `fix-mddb-stats-timeout-overnight`;
follow-up card `mddb-stats-o1-counts` (MEM-0582) created for the real fix.
Not committed/pushed per dispatch rails.
