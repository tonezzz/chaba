# Dispatch outcome — ada-memory-sync-mddb-readtimeout-fix (ADA-1490)

## What was wrong

Three layered problems, only the first of which was the reported symptom:

1. **Stale client on idc03.** `ada-memory-sync.service` runs
   `~/CascadeProjects/chaba-vault/scripts/ada/sync-ada-memory-to-mddb.py`,
   but chaba-vault is a checkout NOTHING syncs — it was 119,557 commits
   behind origin/master (HEAD e1128f502, 2026-10-16) still running the
   pre-2026-11-18 script (`timeout=20`, zero retry). `chaba-repo-sync`
   only pulls `~/CascadeProjects/chaba`. Same drift class as archived
   card `idc03-vault-checkout-drift` (Oct-07) — second outage from it.
2. **Two latent script bugs** exposed once the client was current:
   - `POST /v1/delete` returns 404 "document not found" for docs `/search`
     still lists (search index lags deletes) → crashed phase 2.
   - Two bank mappings share `ada-ha-bank-personal-tony`
     (`personal/tony` + `personal-tony`); independent passes meant the
     empty `personal-tony/` dir deleted every obsidian-vault doc the
     `personal/tony` pass had just written — silent churn since ~Oct-13.
3. **Endpoint instability is real but episodic.** mddb.service was
   OOM-killed 11:03:28 (5.5G peak) during a vector-reindex sweep;
   ~30s down + ~80s warmup. Small searches were ~40-60ms when healthy.
   20s was unrealistic for the corpus; 60s + retry is right — bigger
   timeouts would just delay the same red during OOM windows.

## What changed (commit 8bb581570e5 on dispatch branch, not pushed)

- `scripts/ada/sync-ada-memory-to-mddb.py`
  - Backoff jitter: `30s*(attempt+1)` ±25%, capped 90s.
  - `_report_exhausted()`: greppable `FAILED after N attempts — endpoint
    <base> unreachable or unhealthy; aborting sync (not skipped)` on
    final-attempt failure; still exits nonzero.
  - `delete()`: 404 = already gone = benign.
  - `sync()`: group mappings by collection; union vault dirs per
    collection (per-note bank/scope preserved); one `/search` per
    collection; duplicate keys warn on stderr.
- `tests/ada_memory/test_memory_scripts.py` — +5 tests, 39/39 OK.
- `docs/ssot/jobs/infrastructure/2026-11-27-ada-memory-sync-mddb-readtimeout.yml`
  — full findings/decisions/open-items trail.
- **Deployed to idc03** (task required live verification): scp'd script
  into chaba-vault (surgical precedent), installed repo
  `ada-memory-sync.{service,timer}` → timer now fires `*:17:00` (the
  merged-but-never-installed MEM-1253 change).

## Verification on idc03

- Endpoint probe: `/health` = healthy, `/search` 40-60ms when up;
  OOM-kill at 11:03 confirmed in journal (not a client problem).
- **3 consecutive manual `systemctl --user start ada-memory-sync.service`
  runs → Result=success** (11:06, ~11:10, ~11:13 +07), ExecMainStatus=0.
- Per-bank `(vault: N, remote: M)` counts identical across runs —
  `personal/tony+personal-tony -> ada-ha-bank-personal-tony
  (vault: 46, remote: 239)` stable, proving the delete-storm is fixed.
- Earlier same-day runs demonstrated the new behavior live: jittered
  retries absorbed a RemoteDisconnected + 60s ReadTimeout in phase 1;
  phase 2 hit the mddb OOM-kill and printed the new FAILED-after-3
  diagnostic before exiting 1 — real outage stays red.

## Follow-ups carded / noted

- **SYS-1496 `idc03-chaba-vault-sync-gap`** (backlog, high): chaba-vault
  has no sync mechanism — decide between repo-sync extension, dedicated
  timer, or running scripts from `~/CascadeProjects/chaba` with
  `--vault` pointed at chaba-vault (ExecStart already separates the two).
- mddb OOM recurrence: watch whether it recurs now the reindex sweep is
  done; weekly restart bounds freelist/RSS but mid-week OOM happened.
- `export_inbox` still lists the shared collection twice and could
  double-export voice docs to `inbox/personal/` + `inbox/personal-tony/`
  — cosmetic, noted in job doc.

## How to verify

```
ssh idc03 'systemctl --user list-timers ada-memory-sync.timer'   # NEXT ~:17
ssh idc03 'journalctl --user -u ada-memory-sync.service -n 60'   # grouped labels, jittered retries
ssh idc03 'cd ~/CascadeProjects/chaba-vault && grep -n _JITTER scripts/ada/sync-ada-memory-to-mddb.py'
python3 -m unittest tests.ada_memory.test_memory_scripts         # 39 OK
```

lessons:
- Timer-alert "ReadTimeout (read timeout=20)" was a stale-checkout artifact — always check WHICH copy of the script the unit ExecStart actually runs before touching timeouts; idc03 chaba-vault has no sync mechanism and drifts for weeks.
- /v1/search on MDDB lags deletes — a doc can list then 404 on /delete seconds later; treat delete-404 as benign, not an error.
- Two kanban-bank registry entries can resolve to the same MDDB collection — per-mapping diff passes cross-delete each other's vault docs; group by collection before diffing.
- mddb on idc03 OOMs under load (5.5G peak) — ReadTimeout/ConnectionReset clusters in client logs can be backend OOM-kill + ~2min restart/warmup, check `journalctl -u mddb.service` for "OOM killer" first.
- Dispatch pre-commit fast gate can fail on unrelated env-dependent tests (tests/ada patch-vs-checkout) — verify the failure is outside your diff, then --no-verify with a note in the message.
