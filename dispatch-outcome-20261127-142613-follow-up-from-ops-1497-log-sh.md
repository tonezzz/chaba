# Dispatch outcome — mddb-ops-write-congestion-stagger-timers (OPS-1502, attempt 2)

## Context

Attempt-2 run: zombie-claim restart (OPS-1071) after attempt-1
(`dispatch/20261127-131736-...`) merged a38522d8 → origin/master and the
card auto-closed at 14:25. The card's open board request — Tony-approved
kill of the mddb-ops deleteWhere drain loop on idc03 — was answered at
14:20 but **never executed**: the auto-close dropped the action
("answer recorded but no active action"). This run closed that gap.

## What I did

1. Verified attempt-1 state: correlation + stagger already merged;
   card `column: done`; request `mddb-ops-deletewhere-drain-loop-...`
   status=answered (APPROVED: kill pid 3862968 NOW, client-side only).
2. Confirmed the drain loop was still alive on idc03: bash loop pid
   3862968 (3h38m, PPID=1) + in-flight child `prune-old-docs.py` pid
   269016; `/tmp/prune-drain.log` tail = every iteration
   "deleteWhere failed — timed out (deleted 0 before failure)".
3. Executed the approved kill: `kill -TERM 3862968 269016` over ssh;
   verified both gone and `pgrep -af prune` empty — no respawn possible.
4. Verified recovery (consumer proof, not just producer):
   - mddb-ops journal since kill: every `deleteWhere` "response not
     delivered" completion has arrival ≤13:57 (completion − elapsed) —
     all pre-kill orphans draining; warning rate decaying
     (elapsed 3450s → 2530s). Zero add/ingest/search write-timeout
     warnings since ~14:40.
   - `POST /v1/stats` → 200 in **11ms** (was 154s at 13:32).
   - `POST /v1/add` probe doc → 200 in **3.8s** (was 125–198s during
     congestion). `POST /v1/delete-collection` cleanup → 200 in 12.7s.
     Probe collection `devin-latency-probe` removed afterwards.
5. Fixed a latent defect in the merged job doc:
   `docs/ssot/jobs/mddb/2026-11-27-write-congestion-stagger-timers.yml`
   `followups:` block was invalid YAML as merged (unquoted `- ` items
   containing `: `); quoted the items and appended a `post_kill_verify`
   section + status update. `yaml.safe_load` now passes.

## Result

Done-when met: the herd theory was already disproven as primary cause
by attempt-1 data; the dominant deleteWhere storm is now stopped at the
source and mddb-ops write latency recovered to healthy levels. The
staggered shipper timers remain merged-but-uninstalled (deploy gate —
dispatch does not deploy); with the storm gone they are belt-and-braces,
not urgent.

## Residual risks / follow-ups (documented in job yml)

- `prune-old-docs.timer` (idc03 **user** unit, daily 09:30,
  `--budget-seconds 0`) is NOT declared in `ssot.jobs.yml` — host-hygiene
  gap (MEM-0871 lineage). It will retry the ~390k-doc host-logs backlog
  tomorrow 09:30; it execs the `~/CascadeProjects/chaba` checkout so
  chaba-repo-sync delivers attempt-1's backoff-fixed script — watch that
  run.
- Orphaned server-side deleteWhere handlers from pre-kill arrivals may
  keep completing silently for up to ~80min; no new ones can be created
  (only remaining deleteWhere producers are the daily prune timer and
  device-telemetry-prune at 04:23).
- idc03 capacity (15GB/4-core VPS ~13GB used) remains a Tony spend
  decision — see idc03-structural-capacity / SYS-0151 history.

## How to verify

- `pgrep -af prune-old-docs` on idc03 → empty.
- `journalctl --since <kill> | grep "response not delivered"` on idc03 →
  deleteWhere completions only, arrivals all ≤13:57; no add/ingest
  warnings.
- `curl -w '%{time_total}' http://100.102.134.91:11026/v1/stats` → ~ms.
- Card comms on `mddb-ops-write-congestion-stagger-timers` have the
  full trail; job doc has the `post_kill_verify` block.

lessons:
- Board request answers do NOT execute themselves — an auto-close between answer and pickup silently drops the approved action; attempt-2 zombie restarts are the safety net, check "answer recorded but no active action" comms.
- journalctl "handler finished after write timeout" elapsed includes queue wait — always compute arrival = completion − elapsed before correlating with client timers.
- `- ` YAML sequence items containing `: ` must be quoted or they parse as mappings and can break multi-line plain scalars — job docs under docs/ssot/jobs/ aren't covered by the card-YAML merge driver, so invalid YAML merges silently.
- systemctl --user units are invisible to plain `systemctl cat/list-timers` — fleet shipper/prune timers live in ~/.config/systemd/user/.
- Detached `while true` remediation loops are undeclared infra — the drain loop amplified the failure it was fixing; SIGTERM parent-then-child in one ssh kills both loop and in-flight iteration.
