# Dispatch outcome — timer-alert-tony-dell-tony-dell-mcp-health

## What was found

The card flagged `tony-dell-mcp-health.service` on tony-dell with
`result=exit-code` (last cited run 2026-10-14 19:44). Investigation of
`journalctl --user -u tony-dell-mcp-health.service` on tony-dell showed:

- The user journal only reaches back to Oct 20 — the Oct-14 run is beyond
  retention and cannot be reconstructed.
- The journal does show a **sustained failure window Oct 21 09:36 → Oct 22
  16:43 (+07)**: ~373 consecutive `exit-code` runs, each failing in ~1-4s,
  then full recovery — all runs OK since 16:48:47.

## Root cause

`chaba-postgres.service` (quadlet `chaba-postgres-16`, pgvector/pg16) on
**idc03** was restarted Oct 21 09:35:57. The restart raced:

- Two recreated containers failed `rootlessport listen tcp 127.0.0.1:5432:
  bind: address already in use` (status=126).
- A third attempt (09:36:19, container `f05cae59`, revised port map
  `127.0.0.1:5433` + `100.102.134.91:5432`) started and stayed **healthy
  internally** — but the external tailscale-IP listener
  `100.102.134.91:5432` was never actually serving, so remote postgres
  connects were refused for ~31h. Local consumers (`127.0.0.1`) were
  unaffected, which masked the outage.

Failure mechanism of the timer:

- `tony-dell-mcp-health.sh` ssh's to tony-omen and runs
  `POSTGRES_HOST=100.102.134.91 mcp-health-client.py get_health_score`.
- The mcp-health server (`server.js`) runs `initializeDatabase()` at module
  load; on `pool.connect()` refusal it calls `process.exit(1)` within ~0.5s.
- The client then hits `BrokenPipeError` writing to the dead server's stdin
  → exit 1 → ~1s failure signature (observed every run).

Reproduced exactly: pointing `POSTGRES_HOST` at a refused port produces the
identical rc=1 in ~0.8s.

A/B proof: sibling `tony-dell-monitor.sh` runs the same remote query but
with the default `POSTGRES_HOST=100.68.142.13` (tony-dell's own postgres,
which stayed up) — it succeeded every run during the same window.

## Recovery (already done before this dispatch)

Oct 22 ~16:47 a session from mn01 (100.106.196.22) ran `sudo ss -tlnp` on
idc03 (port diagnosis), then `chaba-postgres.service` restarted at
16:48:35, restoring the `100.102.134.91:5432` rootlessport bind. First
timer success 16:48:47; all runs green since (verified through 19:34).

## Current state — verified

- `tony-dell-mcp-health.timer`: active (waiting), next trigger in ~4min.
- `tony-dell-mcp-health.service`: last run `status=0/SUCCESS`.
- `chaba-postgres.service` on idc03: active since 16:48:35; rootlessport
  binds `100.102.134.91:5432` and `127.0.0.1:5433` both listening.
- `~/var/chaba/health/tony-dell-mcp-health.json` updating each run
  (overall_score 38 — several services "unknown" is pre-existing config
  drift, unrelated to this incident).

## Follow-ups carded in the trail doc

`docs/ssot/jobs/monitoring/2026-10-22-tony-dell-mcp-health-timer-alert.yml`

1. **mcp-health ↔ postgres coupling** — server.js `initializeDatabase()`
   does `process.exit(1)` when pg is unreachable, so `get_health_score`
   dies instead of reporting postgres as down. The monitor depends on the
   thing it monitors; degrade gracefully.
2. **stderr discarded** — `tony-dell-mcp-health.sh` uses `2>/dev/null`,
   so the remote traceback never reaches the journal. Append stderr to
   `~/var/chaba/health/tony-dell-mcp-health.err` instead.
3. **Sentinel staleness** — the card cited a 10-14 single failure while a
   31h continuous outage Oct 21-22 didn't surface as a fresh escalation;
   check timer-sentinel re-alert cadence.

## How to verify

```bash
ssh tony-dell 'systemctl --user status tony-dell-mcp-health.timer; \
  journalctl --user -u tony-dell-mcp-health.service -n 12 --no-pager'
ssh idc03 'systemctl --user status chaba-postgres.service --no-pager | head -5; \
  ss -tlnp | grep 5432'
# expect: service status=0/SUCCESS on recent runs;
#         100.102.134.91:5432 + 127.0.0.1:5433 bound by rootlessport
```
