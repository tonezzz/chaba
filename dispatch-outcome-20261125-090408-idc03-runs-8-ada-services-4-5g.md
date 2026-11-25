# Dispatch outcome — idc03 structural capacity (15GB/4core)

Card: `idc03-structural-capacity-15gb-4core-per-2d787f`
Date: 2026-11-25 · Executor: devin-dispatch (ran on idc02, drove idc03/omen/mn01 over ssh)

## Result: DONE — idc03 MemAvailable ~4.4Gi -> ~6.9Gi (>=4GB headroom met, no spend)

## What was found (real numbers)

idc03 (15Gi): used 11.5G, available ~4.4Gi, swap 4Gi 100% used, load5 ~12/4 cores.

Per-unit RSS (systemd MemoryCurrent; containers cross-checked vs /proc smaps anon):

| resident | RSS | note |
|---|---|---|
| mddb main (:11023) | 1.46G | real anon 1.37G |
| mddb-cms (:11027) | 1.72G | real anon 1.35G |
| board-api | 2.07G→0.5G | ~150MB/h ratchet, capped + restarted |
| ollama | 1.80G | mostly transient bge-m3 (5m keep-alive) |
| mddb-ops (:11026) | 0.40G real | cgroup showed 2.95G — page-cache inflated |
| litellm | 0.62G | core infra |
| ada-dev + ada-kk-dev | 0.66G | residual — STOPPED this session |
| jev (jevos :8017) | 0.71G | load-bearing (loop-gate/code-decision/dispatch_repos), runs in ssh session scope not systemd — hygiene gap, not touched |
| doc-archive | 0.33G | assessed, migration skipped |
| ~8 prod ada-* services | ~1.5G combined | stay |

mn01 rejected: 684Mi available. omen: 12Gi available (load ~66 — watch).

## What was done

1. **Completed the twin migration (option b)** — phase-1 (11-18) moved ada-dev/ada-kk-dev + jev-student to omen but left the twins active on idc03 AND the omen copies bound 127.0.0.1 (unreachable from idc03 ever since; "verified HTTP 200" was localhost-only). This session:
   - omen units rebound to `--host 100.75.102.88` (tailnet IP only).
   - **Latent outage fixed**: omen ada-voice/.venv was relocated from ada-pi — all 24 console-script shebangs pointed at the deleted `ada-pi/.venv`; any restart would 203/EXEC. Rewrote shebangs, verified uvicorn.
   - Verified from idc03: HTTP 200 ~30ms, `/ws` 403 = same auth-gated parity as local twin; secrets md5-identical.
   - Repointed consumers: `ADA_LIVE_URL` in ada-scenario-{smoke.container,cms,reports,research} → `ws://100.75.102.88:8005/ws`; `LINE_NAME_BACKENDS` dev entries in line-bot.env → omen (relay restarted). ada-kk-dev had zero consumers.
   - Stopped+disabled both twins on idc03 (~656MB). Guard comments added to unit files.
   - Paid-lane guard still classifies :8005/:8009 as FREE lane (port-based check — verified).

2. **board-api leak (option d)** — root cause: `load_cards()` re-read + re-parsed the ~14MB cards.json on EVERY `/cards|/card/*|/queue` call (~150MB transient allocs/call → RSS ratchet). Fix committed on dispatch branch: `_cards_json_payload()` caches by (mtime_ns,size) signature, no caching on failed reads, shallow-copy return. Live mitigation on idc03: `chaba-board-api.service.d/memory-cap.conf` MemoryHigh=1600M/MemoryMax=2200M + restart (2.07GB→34MB; writes are atomic so OOM restart is safe).

3. **Provider-gate fix (found while verifying)** — `scenario-provider-gate.py` ExecCondition requires `systemctl --user is-active ada-dev` locally; stopping the twin would have gated every dev-lane suite 'infra' forever. Added `--live-url` remote mode (HTTP probe instead of systemctl, journal quota probe skipped — in-suite sentinel is the backstop, free-lane sha check unchanged). Deployed to `~/.local/share/ada-scenario-runner/scenario-provider-gate.py` on idc03 + repointed the 4 ExecConditions (smoke/cms/reports/research) with `--live-url http://100.75.102.88:8005`. First post-change run gated infra under the old script (honest skip); new gate verified `--dry-run` ok and a live smoke run started 09:35 with ExecCondition SUCCESS — end-to-end verification in progress.

4. **MDDB consolidation (option c)** — assessed, rejected: mddb+mddb-cms are separate 4.8G/18G DBs; mddb-ops real RSS only 400MB (cgroup figure was page-cache). Not a cheap win.

5. **Resize (option a)** — NOT needed: non-spend options recovered >2.5Gi headroom. Documented in `docs/ssot/jobs/infrastructure/2026-11-25-idc03-capacity-twin-migration-boardapi-cap.yml`.

## Open items (documented, not blocking)

- **deploy-ada.sh SERVICES** still lists ada-dev/ada-kk-dev → next idc03 fleet deploy resurrects ~656MB. Recommended one-line patch (drop twins from the idc03-default list) is in the SSOT job file `open_items` — ada-voice repo, couldn't push from dispatch.
- board-api payload-cache + gate `--live-url` fixes ride dispatch branch → master → idc03 checkout pull; board-api needs a restart to load the cache fix (MemoryMax covers the gap); gate ExecConditions already run the runner-dir copy so suites are unblocked NOW.
- idc03 swap still 100% used — left alone (self-managing; swapoff adds I/O under load 8-12).
- ada-scenario-smoke "report write failed: timed out" clusters are PRE-EXISTING (seen 04:00/06:00 today, 274 in 3d) — mddb :11023 leader embeds report posts inline and dies under embedding-queue pressure; unrelated to this change.
- jevos (`jev serve` :8017) runs in an ssh session scope, not systemd — survives only while session-670 lives; should get a proper unit (hygiene, separate card-worthy).

## How to verify

- `ssh idc03 'free -m'` → available ~6.9Gi
- `ssh idc03 'systemctl --user show chaba-board-api -p MemoryCurrent,MemoryMax'` → capped 2.2G
- `ssh idc03 'systemctl --user is-active ada-dev ada-kk-dev'` → inactive/disabled
- `ssh idc03 'curl -s -o /dev/null -w "%{http_code}" http://100.75.102.88:8005/'` → 200
- `ssh tony-omen 'systemctl --user is-active ada-dev ada-kk-dev'` → active, `ss -tln | grep 800` → 100.75.102.88 binds
- `ssh idc03 'journalctl --user -u ada-scenario-smoke.service --since "09:35"'` → ExecCondition status=0, container Up, scenarios executing vs omen (manual run in progress; hourly timer also fires 10:00)

## Files changed (worktree, dispatch branch)

- `scripts/board/board-api.py` — `_cards_json_payload()` signature cache
- `scripts/ada/scenario-provider-gate.py` — `--live-url` remote provider mode
- `docs/ssot/jobs/infrastructure/2026-11-25-idc03-capacity-twin-migration-boardapi-cap.yml` — full job record

Host-side changes (no repo): omen unit ExecStart binds, omen .venv shebangs, idc03 scenario unit/container envs, line-bot.env, idc03 twin stop/disable + guard comments, board-api memory-cap drop-in + restart.

lessons:
- "systemd --user MemoryCurrent for quadlet containers includes page cache — mddb-ops showed 2.95G but real anon RSS was 71MB; verify with /proc/<pid>/smaps_rollup Anonymous before believing cgroup memory."
- "Relocating a python venv breaks console-script shebangs silently — running processes survive on the old interpreter until restart, then 203/EXEC; grep .venv/bin/* for the old path after any move."
- "A 'migrated' service bound to 127.0.0.1 is unreachable from the tailnet — verify migrations from the CONSUMER host, not localhost; phase-1 'verified HTTP 200' was localhost-only and the omen twins served zero real traffic for a week."
- "LINE_NAME_BACKENDS in line-bot.env is a second consumer surface for dev-twin ports — repointing scenario units alone misses it."
- "ada-scenario-smoke 'Failed/timeout' after a completed run is a pre-existing TimeoutStartSec quirk; 'report write failed: timed out' clusters are a known mddb-:11023 inline-embedding queue issue, not a regression signal."
