# Dispatch outcome — log-shipper-mddb-heartbeat-timeout-fix (OPS-1497)

## What changed

`scripts/ada/log-shipper.py` — client write budgets were all below
mddb-ops' real latency, producing fleet-wide false failures:

- `_post()` gained an `attempts` param: retries transport/5xx, 4xx
  fails fast; deterministic keys make replays idempotent.
- Heartbeat (`post_state()`) and the per-doc `/add` fallback now use
  `ADD_TIMEOUT=130, ADD_ATTEMPTS=2` (was 10s / 15s default).
- `_ingest()` timeout 60 → 130, deliberately no retry (re-posting a
  timed-out batch would double write load on a congested server).

`ansible/playbooks/log-shipper.yml` — hardened
`shipper_changed_dests` (`map(attribute='dest', default='')` +
select truthy); `--check --diff` crashed on mn01 without it.

`docs/ssot/jobs/infrastructure/2026-11-27-log-shipper-mddb-write-budget.yml`
— full investigation/fix/verification trail.

## Deviation from card spec (documented on card + job doc)

Card asked heartbeat ~45s ×2. Implemented **130s ×2**: mddb-ops'
`MDDB_HTTP_WRITE_TIMEOUT` is 120s and its journal shows `/add`//`/ingest`
handlers running 125–198s during congestion waves — a 45s budget still
false-fails every wave (proven live: omen-severe v1 run shipped all 311
docs then failed heartbeat at 45s). 130s sits just above the server's own
deadline so the client sees the server's verdict; genuine outages still
exit non-zero (conn-refused fails in ms, >deadline still fails).

## Deploy + verification

- Converged via `ansible/playbooks/log-shipper.yml` from this worktree:
  fixed script → `~/.local/share/log-shipper/log-shipper.py` on all 6
  hosts (tony-dell, tony-omen, idc02, idc03, mn01, con01); mn01's stale
  `TimeoutStartSec=600` units also refreshed to 2700.
- Triggered all 14 lanes manually; results (all v2):
  - idc02: full 235/0 ✅, severe 240/0 ✅
  - tony-omen: full 790/0 ✅ (38min backlog drain), severe 218/0 ✅
  - tony-dell: full 534/0 ✅, severe 251/0 ✅, mha + severe-mha ✅
    (michael-ha reachable:True, genuinely quiet)
  - idc03: full 852/0 ✅, severe 291/0 ✅
  - con01: full 20/0 ✅, severe 26/0 ✅
  - mn01: severe 193/0 ✅; **full lane hit TimeoutStartSec=45min**
    draining backlog (1846 matched → 1360 shipped, 0 failed, cursor
    checkpointed, ship/mn01 fresh failed:0) — honest timeout, not the
    heartbeat bug; re-run in flight to drain the remainder.
- Fresh `host-logs-state` `ship*/<host>` docs confirmed for every lane.

## Cards

- Closed green via board-api with evidence comments: idc02 ×2,
  tony-dell ×4, mn01-severe, omen-severe, omen-full = **9 of 10**.
- `timer-alert-mn01-log-shipper` left open with status comment — its
  full lane timed out on backlog drain (real timeout), re-run triggered;
  closes when a run finishes green.

## How to verify

- `systemctl --user status log-shipper.service` on any host →
  Result=success; `journalctl --user -u log-shipper.service` shows
  "N shipped (... 0 failed)" with no "heartbeat write failure" line.
- `POST http://100.102.134.91:11026/v1/search {"collection":"host-logs-state"}`
  → fresh `ship/<host>` docs, `failed:0`, `reachable:true`.
- Deployed script hash: `sha256sum ~/.local/share/log-shipper/log-shipper.py`
  on any host == worktree `scripts/ada/log-shipper.py`.

lessons:
- [log-shipper-timeout-fix] mddb-ops client budgets must exceed the server's own MDDB_HTTP_WRITE_TIMEOUT (120s): handlers keep running and finish the write after the client gives up — "response not delivered" in server logs = false failure, not an outage. Card spec's ~45s was still too small; live verification caught it.
- [log-shipper-timeout-fix] Fleet timer sync (:50-:52 hourly, all hosts at once) creates thundering-herd congestion waves on mddb-ops — likely the root cause of the 125-198s handler times; staggering schedules is a separate card-worthy fix.
- [log-shipper-timeout-fix] ansible --check --diff result dicts can lack 'dest' — map(attribute='dest') crashes; use default='' + select('truthy').
- [log-shipper-timeout-fix] systemd oneshot TimeoutStartSec kill exits cleanly via the shipper's _STOP checkpoint (partial progress saved, heartbeat still posts) but unit Result stays 'timeout' — backlog-drain timeouts are honest failures, distinct from write-budget false failures.
