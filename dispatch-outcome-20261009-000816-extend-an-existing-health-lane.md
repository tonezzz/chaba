# runner-bootstrap-check — runner-fleet-health lane

## What changed

- **`scripts/board/runner-fleet-health.py`** (new, ~590 lines) — a
  cms-auto-health-style lane. Each tick it probes every dispatch host
  parsed out of `ssot.kanban.yml` `runner_fleet` (regex over the
  `'<host>:'` labels; `RUNNER_FLEET_HOSTS` env override, 6-host
  hardcoded fallback) and writes `runner-auto-<host>.yml` cards only on
  violation — review on failure, auto-close on recovery, 12h → high
  priority, ghost-sweep closes cards for retired hosts.
  - Probe: one `ssh <host> python3 -` (stdlib only — runner hosts lack
    PyYAML), same shape as merge-sweep's REMOTE_*_PROBE; the local host
    runs it in-process. Collects git committer-ident + global
    name/email, per-repos.conf-entry existence/.git/remote/behind
    (real `git fetch` only for the canonical chaba clone), installed
    `~/.local/bin/runner-agent` + `devin-dispatch`
    presence/exec/syntax/sha256, `dispatch_repos` resolution replaying
    `runner-agent.dr_module()` + import smoke + `close_out` /
    `close_out_notes` attrs, and `devin` binary resolvability via
    devin-dispatch.sh's order.
  - Judge: fetch-only https remotes are NOT violations by themselves —
    per spec, merge-sweep salvage is the push substitute, so it is
    verified from the checker with `git ls-remote <host>:<path>` and
    only flagged when that fails too. Clone staleness limit is
    `RUNNER_FLEET_MAX_BEHIND` (default 200 commits). Missing non-chaba
    repo checkouts are info-notes, not violations.
- **`scripts/ada/kanban-sync.sh`** — runs the lane after
  vcast-auto-health; cards commit+push with the wrapper's existing
  `git add docs/ssot/kanban/cards/` block. Header comment updated.
- **`docs/ssot/infrastructure/ssot.jobs.yml`** — kanban-sync entry now
  lists the lane.
- **`docs/ssot/jobs/kanban/2026-10-09-runner-fleet-health.yml`** —
  design/verification trail.
- **`docs/ssot/kanban/cards/runner-auto-mn01.yml` and
  `runner-auto-idc01.yml`** — real cards from the first live run:
  mn01's chaba clone is 372 commits behind origin/master (dispatch_repos
  still has the needed attrs — drifting but not yet crashing), and
  idc01's installed devin-dispatch sha `1dd91c1f` differs from repo
  `ea6eeaca` (predates the `${MODEL:+--setenv}` guard).

## Acceptance — would the three historical failures be caught?

Verified against `judge()` with synthetic probes and live hosts:

- **mn01 ghost checkout** (dir without .git) → `clone-no-git` violation.
- **idc01 stale clone** (860 behind) → `clone-stale` (>200) AND
  `dispatch-repos` (missing `close_out_notes`) — double-caught, either
  alone would card it.
- **idc03 missing git identity** → `git-identity`
  (`GIT_COMMITTER_IDENT` unresolvable); the https-only remote is
  handled per spec — fetch-only + verified salvage = note only,
  fetch-only + dead salvage = `remote-push` violation.

## Result / verify

`RUNNER_FLEET_HOSTS=mn01,idc01 python3 scripts/board/runner-fleet-health.py`
— exits 0, prints the FAIL lines, writes/updates the cards. Green fleet
prints only the summary line and touches nothing. Cards committed on
the session branch (no push, per rails); the next kanban-sync tick on
tony-dell runs the lane for real — it needs the fleet ssh keys that
live in the tony-dell user context (this session on mn01 could only
reach idc01; tony-omen/idc02/idc03 would read 'unreachable' from here
but are expected reachable from dell).
