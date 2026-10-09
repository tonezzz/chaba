# nest-manager-node — per-host nest-mgr service + live nest-<host> CMS pages

**Result: done.** The nest-mgr observer-governor is installed and running on
idc03, tony-omen, and tony-dell; all three publish `nest-<host>` CMS pages
that are PROPOSED tiles on the /chaba-nest spec.

(Prior attempt never ran — the dispatch died in 1s on a stale runner env and
was false-verified by merge-sweep; this run did the work from scratch.)

## What landed

- `stacks/services/nest-mgr/` — `nest-mgr.py` (self-contained manager,
  stdlib+pyyaml), `nest-mgr.service` (user unit, `--loop` daemon),
  `install.sh` / `verify.sh`, `README.md`. Job record:
  `docs/ssot/jobs/nest/2026-10-09-nest-mgr-service.yml`; linked from
  `ssot.nest-training.yml` related list.
- **Discovery** per host: systemd user units matching
  `jev|student|bankq|nest|serve-*.py|openjev` (name/desc/unit-file contents),
  `serves:`/`lanes:` in `~/CascadeProjects/ada-pi/tests/bench/topologies.yml`
  resolving to the host, live `/metrics` on a fixed known-port list (no port
  scan). Multi-source nodes merge on endpoint port; live units claim the
  name first (a stale `jev-bench.service` file on idc03 correctly merges as
  an alias instead of stealing jev-student's node).
- **Ownership**: `NEST_OWNER=` env/unit-file wins; kanban `nest_nodes:` card
  field claims (`card:<id>`); `NEST_OWNER=none` opts out (`unmanaged`);
  everything else adopted (`owner: manager`).
- **Report**: `ada-cms-pages/nest-<host>` via the MDDB `add` write path
  (report-distill contract — kind=report, domain=bench, fresh_for=30m,
  timeline, links, parent=chaba-nest). One row/node: name · kind · endpoint
  · state · goal · progress (req/esc/uptime/bench) · owner. Publishes every
  15 min, on state-change fingerprint, and on registry `run_now` (the CMS
  regenerate button queues it; the daemon clears it — no ada-pi allowlist
  change needed).
- **Surface**: `docs/ssot/infrastructure/ssot.chaba-nest-dashboard.yml` —
  the three `nest-<host>` tiles added to the `nest` topic as
  `state: proposed` (Tony: `--accept`/`--reject` + `--apply` to push).

## Verified

- `nest-mgr.service` active (running) on idc03, tony-omen, tony-dell.
- `~/.local/share/nest/manager-state.json` on idc03 has **4 adopted nodes**
  incl. jev-student (active, 772 req, bench golden 10/10), bankq-student
  (shadow), openjev-student (active) — ≥3 requirement met.
- `curl -sf http://127.0.0.1:8001/api/cms/pages/nest-idc03` on idc03 → 200
  (x-api-key). **Note:** the card's literal `/api/pages/` path 404s — the
  real CMS route is `/api/cms/pages/{slug}`.
- `chaba-nest-build.py --discover` listed all three pages as candidates
  before speccing; afterwards the `nest` topic shows none (claimed) —
  they still appear under `polity` until accepted/rejected there.
- `./verify.sh` all green; `ssot-validate-all.mjs` 1769 files, 0 errors
  on the new/changed files.
- Observational only — no restarts/enforcement anywhere.

## Live state snapshot

| host | nodes | notable |
|---|---|---|
| idc03 | 4 | jev-student + openjev-student active; bankq-student shadow; open-jev parked (stale unit) |
| tony-omen | 5 | open-jev + open-jev-student **failed** (leash-parked — honest report); orch-bench, open-jev-leash, gtx1650 lane parked |
| tony-dell | 3 | tony-dell-cpu + tony-dell-igpu lanes parked; kanban-brief ops |

## Follow-ups (not blocking)

- Tony accepts PROPOSED tiles → `chaba-nest-build.py --accept nest-idc03 ...`
  then `--apply`.
- Enforcement (restart failed nodes, auto-leash) stays human-gated — separate
  card per the leash posture.
- Optional convention: add `NEST_OWNER=` / `nest_nodes:` where a node should
  not be manager-adopted.
