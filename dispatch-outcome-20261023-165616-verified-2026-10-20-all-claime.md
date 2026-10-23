# Dispatch outcome — migration-stragglers-orphaned-units (2026-10-23)

## Card scope vs. findings

The card listed 6 units. A prior session (2026-10-22) had already repointed the
omen weaviate units; this session re-verified them and cleared the rest.
Beyond the list, dell had more failed units in `systemctl --user --failed`
that were migration-caused and got the same treatment.

## Changes made

### tony-dell (user units)

| Unit | Disposition | Evidence |
|------|-------------|----------|
| ha-auth-watch.service | **Repointed** — `INSTANCES` tony-ha URL `tony-dell.taila0626a.ts.net:8123` → `tony-omen.taila0626a.ts.net:8123` in deployed script (exec checkout) + repo commit `eacb8e1e` | `systemctl --user start` → Result=success, "polled 2 instance(s): 1 new auth-failure line(s) (1 deduped), 0 error(s)" — it even surfaced a real localhost auth failure on tony-ha |
| network-scan-tony.service | **Repointed** — unit `WorkingDirectory`/`ExecStart` moved from `~/CascadeProjects/chaba-tony-dell` (readonly mirror, role violation) → `~/CascadeProjects/chaba` (exec checkout). Created `~/CascadeProjects/chaba/venv` with PyYAML==6.0.3 + websockets==17.1 (mirrors old venv). `ssot.jobs.yml` entry updated in same commit. | Verified run: 18 hosts scanned on 192.168.2.0/24, "Pushed tony-ha Devices view (50 rows)" — writes now land in exec checkout (generated paths are gitignored either way) |
| yomi-api.service | **Retired** — quadlet source was already in `migrated-off/`; daemon-reload dropped the generated unit; reset-failed. yomi-api verified active on idc03. | `systemctl --user --failed` no longer lists it |
| trade-automation.service | **Retired** — `~/.config/containers/systemd/trade-automation.container` → `migrated-off/`; stopped+disabled; reset-failed. trade-api verified running on idc03. | cleared |
| ssot-optimization-snapshot.{service,timer} | **Retired on dell** — stale duplicate; `ssot.jobs.yml` declares `host: idc02`. Files → `~/.config/systemd/user/migrated-off/`, timer disabled, reset-failed. | idc02 copy re-ran clean (Result=success) — the 03:30 failure was a transient SSOT validation error, already healed upstream |
| raceman-php.service | **Cleared** — podman-generated unit whose container no longer exists anywhere; reset-failed. | cleared |

### tony-omen (user units)

| Unit | Disposition | Evidence |
|------|-------------|----------|
| weaviate-index / weaviate-search | Already repointed to `WEAVIATE_URL=http://100.123.163.11:8084` (idc02) by prior session — re-verified: index Result=success, search active since 10-22 | `curl localhost:3002/search` returned real hits |
| weaviate-embed-proxy | Verified live — `localhost:5000`→`mn01:5000` chain works (search needs embeddings); **mn01 is up** (spec's "offline 6d" was stale) | HTTP 404 on `/` = server responding |
| mcp-health-snapshot | Verified — Result=success | `systemctl --user show` |
| clip-sync-dell | Stale failed state from earlier parking — `reset-failed` | removed from failed list |

## Left in failed state (NOT migration — flagged, not fixed here)

- **dell `cms-h3-publish` + `mcp-debug-h3-sync`** — `git push` of `chaba.h3`
  rejected (non-fast-forward; checkout behind remote). Fixing unattended means
  a rebase/reset on a satellite checkout — left for a decision.
  `chaba-jobs.service` shows failed only as downstream of these.
- **dell `system-report-watchdog`** — exits 1 *by design* when it raises
  alerts (currently flagging missing producer reports — separate issues).
- **omen**: `ada-pi-orch-bench` (student endpoint 100.75.102.88:8778 remote-
  disconnects — the ada-pi box, not mddb), `ada-review-refresh` (subprocess
  timeout), `focus-dispatcher-overnight` (same transient SSOT validation,
  next run should clear), `model-bench` (30m timeout, slow llama on idc03),
  `xiaomi-token-refresh` (expired passToken cookie — needs browser re-login),
  `wp-cam-snapshot` (spec: pre-existing), desktop portals.
- idc02 `ssot-optimization-snapshot` itself — re-ran green; note
  `ssot-optimize.mjs` `execSync` hard-fails on any transient validator error.

## Repo changes (committed on `dispatch/20261023-165616-verified-2026-10-20-all-claime`, NOT pushed)

- `scripts/audits/ha-auth-watch.py` — tony-ha URL → tony-omen
- `docs/ssot/infrastructure/ssot.jobs.yml` — `network-scan-tony` exec/cwd →
  exec checkout + note

Note: deployed copy of ha-auth-watch.py on dell was edited in place (identical
to the commit) so the exec checkout stays consistent when the branch merges.

## Caveats

- `ha-auth-watch --git` commits focus-inbox alerts from the dell exec
  checkout — works today (no armed pre-commit hook there) but is off the
  single-writer model; long-term the alerts should route via board-api
  `/inbox`. Flagged in card comms.
- If `ssot.jobs.yml` is re-rendered on dell before this branch merges,
  `network-scan-tony` reverts to the mirror path — harmless (still works),
  just the wart returns until merge.

## How to verify

- `ssh tony-dell 'systemctl --user --failed'` — no migration units listed.
- `ssh tony-dell 'systemctl --user show ha-auth-watch.service -p Result'` → success.
- `ssh tony-omen 'curl -s -X POST localhost:3002/search -d "{\"query\":\"x\",\"limit\":1}" -H "Content-Type: application/json"'` → results.
