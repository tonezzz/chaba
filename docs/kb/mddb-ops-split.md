# MDDB ops split — migration plan

Goal: move high-volume append-only telemetry off the authoritative
leader (idc01) so the semantic index stays small and fast. Vector
index cold start is currently ~2h on 21k docs; ~80% of that is
telemetry that never needs embeddings.

## Target topology

```
idc01  mddb leader :11023 (wr)          — banks, CMS, SSOT, KB, reports
       semantic embeddings ON (ollama gemini-embedding-2)
       ~4k docs — index load minutes, not hours

idc02  mddb-ops    :11025 (wr)          — telemetry, append-only
       embeddings OFF entirely (no provider env)
       expendable — rebuildable from writers, no backup SLA

idc02  mddb-lab    :11024 (ro snapshot) — nightly file-copy of leader

tony-dell          follower (ro)        — geo DR of leader only
```

## Collection assignment

**Move to mddb-ops** (~17.2k docs — 80% of today's index):

| collection | docs | writers |
|---|---|---|
| host-logs | 11,110 | log-shipper.py |
| ada-ha-events-* | 3,667 | event_recorder, realtime_provider |
| ada-ha-scenario-reports | 940 | scenario-report/benchmark/prune |
| ada-ha-snapshots-* | 540 | tool_runner (cam/action snaps) |
| ada-ha-recall-summary-* | 266 | conversation_memory, summary_rollups |
| ada-ha-actions-* | 166 | tool_runner action log |
| yomi-digest | 487 | digest-to-mddb.mjs |

**Keep on leader** (~4.1k docs — semantic content):

- `ada-ha-bank-*` (all memory banks — tony, kk, handoff, general, …)
- `ada-cms-pages`, `ada-cms-automation`
- `ada-ha-reports-*`, `ada-ha-device-safety/confidence-*`
- `infrastructure-ssot`, `kb-*`, `chaba-docs`, `chaba-archive`,
  `chaba-architecture`, `devin-kb`

Scenario reports ride with ops — they're run output, not user memory.
(If we want them searchable by meaning later, promote to leader.)

## Code changes

**ada-pi `backend/mddb_client.py`** — add a second client:

```python
MDDB_OPS_URL = os.environ.get("MDDB_OPS_URL") or MDDB_BASE_URL

OPS_COLLECTIONS = (
    "host-logs", "ada-ha-events-", "ada-ha-actions-",
    "ada-ha-snapshots-", "ada-ha-recall-summary-",
    "ada-ha-scenario-reports", "yomi-digest",
)

def for_collection(name: str) -> MddbClient:
    """Route by collection prefix — ops streams go to mddb-ops,
    everything else to the leader. Prefix match, not exact, so
    per-instance names (ada-ha-events-tony) just work."""
    if any(name.startswith(p) for p in OPS_COLLECTIONS):
        return ops_client()
    return default_client()
```

Every write site swaps `mddb()` for `for_collection(name)` — the
routing lives in one place; writers keep their collection names.

**Writer sites to touch** (each is a 1-line client swap):

- `backend/event_recorder.py` — `ada-ha-events-{instance}`
- `backend/realtime_provider.py` — `_ops_collection` writes
- `backend/tool_runner.py` — snapshots + actions collections
- `backend/conversation_memory.py` — recall-summary writes
- `backend/summary_rollups.py` — recall-summary rollups
- `chaba/scripts/ada/log-shipper.py` — host-logs (`MDDB_OPS_URL` env)
- `chaba/scripts/ada/ops-report.py` — reads host-logs for reports
- `scripts/digest-to-mddb.mjs` — yomi-digest
- `scripts/scenario-*.py` — scenario reports

**Reads that cross the boundary**: `ops-report.py` and any Ada tool
that reads events/actions (recall paths) must query `ops_client` for
ops collections. `for_collection` handles this symmetrically.

## mddb-ops instance (idc02)

Quadlet `mddb-ops.container`, port **11025** tailnet-only:

```
MDDB_MODE=wr
MDDB_REPLICATION_ROLE=standalone
# NO MDDB_EMBEDDING_* — provider unset means no vector index at all
MDDB_DATA_DIR=/var/lib/mddb-ops
```

No embedding provider → no index load → cold start in seconds.
Retention: TTL or a nightly prune job (host-logs older than 30d are
dead weight — pick the policy when we see growth).

## Migration steps

1. **Stand up mddb-ops** on idc02 (quadlet, no embeddings, tailnet :11025)
2. **Ship the client change** to ada-pi staging on idc02 — run
   `camera_describe` + a scenario against ada-lab; verify ops writes
   land on 11025 and bank reads still hit the leader
3. **Set `MDDB_OPS_URL=http://100.123.163.11:11025/v1`** in ada-ha env
   on idc01; redeploy via deploy-ada.sh
4. **Verify split**: writes to `ada-ha-events-tony` appear on idc02,
   `ada-ha-bank-*` on idc01; CMS unaffected
5. **Historical data** — leave existing ops collections on the leader
   initially (read-only residue). Optional: bulk-copy to ops then
   delete from leader in a separate step *after* writers are confirmed
   repointed — never delete first
6. **Vector index benefit**: once the leader's ops collections are
   deleted and it restarts, index load drops from ~2h to minutes
   (~4k semantic docs)

## Rollback

Unset `MDDB_OPS_URL` → every client falls back to the leader. No data
loss either direction; ops collections on idc02 are re-pullable from
the writers' sources (logs, events regenerate).

## What this buys

- idc01 index: 21k docs → ~4k, cold start ~2h → minutes
- Restart/reindex no longer a weekly outage risk
- mddb-ops can be wiped/rebuilt freely — telemetry, not memory
- Clear growth story: banks/CMS scale on the leader, telemetry scales
  on the expendable node

## Explicit non-goals

- idc01 stays leader — idc02 is lab + expendable ops, never authoritative
- No live replication between leader and ops (the OOM lesson)
- tony-dell follows only the leader — it doesn't need telemetry
