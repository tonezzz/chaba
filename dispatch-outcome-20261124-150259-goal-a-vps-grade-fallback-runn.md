# Dispatch outcome — idc02-second-ada-pi-lane (OPS-0599)

Date: 2026-11-24 · Host: idc02 · Worktree branch: `dispatch/20261124-150259-goal-a-vps-grade-fallback-runn`

## Result: PASS — all four card steps verified end-to-end

idc02 is now a working VPS-grade fallback lane for ada-pi/ada-voice
dispatches. tony-dell remains the canonical edit point; idc02 joins the
shared dispatch queue with verified push creds.

### (a) Distinctive label — DONE

- `~/.config/systemd/user/runner-agent.service.d/vps-lane.conf` (new):
  `RUNNER_LABELS=ssd,always-on,cpu,small,push:chaba,push:ada-voice,vps`.
  Drop-in sorts last → wins over `ada-pilot.conf`. Chose `vps` over
  `staging` (idc02's ada-voice checkout IS the staging checkout — the
  label would misdescribe scope); `vps` is fleet-unique today.
- `~/.config/systemd/user/kanban-dispatch.service.d/vps-lane.conf`
  (new): `KANBAN_HOST_LABELS` mirrors the set; also repointed
  `ExecStart` off `~/CascadeProjects/chaba-tony-dell` (a scripts/-only
  scaffold with an Oct-16 kanban-dispatch.py and no docs/ssot — the
  unit was un-runnable) onto the synced exec checkout
  `~/CascadeProjects/chaba`, and set `BOARD_API` to the tailnet route
  (script default 127.0.0.1:8787 has no listener on idc02).
  `systemctl --user daemon-reload` done; `systemctl show` confirms env.

### (b) Checkout/remote/worktree — VERIFIED

- `~/CascadeProjects/ada-pi` → symlink to `~/CascadeProjects/ada-voice`.
- Push remote: `pushurl git@github-ada-pi:tonezzz/ada-pi.git` (ssh
  alias → github.com, dedicated key). `git push --dry-run
  origin HEAD:refs/heads/__runner-push-probe` → rc=0.
  `git ls-remote` main SHA identical on fetch (ada-voice.git) and push
  (ada-pi.git) URLs — GitHub rename redirect, same repo.
- `devin-dispatch` builtin repo table resolves `ada-pi`/`ada-voice` →
  `~/CascadeProjects/ada-voice@main`; worktree flow
  `git worktree add ~/CascadeProjects/dispatch-wt-<id> -b dispatch/<id>
  origin/main` proven by existing ada-voice dispatch-wt worktrees and
  29 historical ada-pi/ada-voice task dirs on this host.
- Merge test gate for ada-pi = `pytest tests -k 'not slow'` under
  `~/CascadeProjects/ada-voice/.venv` — pytest 9.2.0 present.

### (c) Canary — PASS end-to-end

- OPS-0029 (`idc02-vps-lane-canary`, priority:low) starved in claim
  order — defer comms kept refreshing `updated`, ~9 cards ahead. Closed
  and re-queued as OPS-0034 (`idc02-vps-lane-canary-hv`, priority:high).
- 15:51 idc02 runner-agent claimed it (only host with `vps`; idc03/
  mn01/con01 correctly deferred 'unclaimable by declared fleet').
- `devin-task-20261124-155106` ran repo=ada-pi, executor=devin,
  model=swe-2-flash-medium in a dispatch-wt worktree; session committed
  `docs/canary/idc02-vps-lane-hv.md` (4da86c9), exit 0.
- Close-out: branch pushed to origin via github-ada-pi ssh → auto-merged
  `2e9a1eeb` → `origin/main` → pytest gate PASSED (206.1s) → worktree
  GC'd. Consumer proof: `origin/main:docs/canary/idc02-vps-lane-hv.md`
  exists with expected content.

### (d) SSOT/docs — DONE (committed on this branch)

- `docs/ssot/kanban/ssot.kanban.yml` runner_fleet prose: idc02 labels
  updated (also clears the queue-time 'unclaimable' warning once merged
  + synced to the writer checkout).
- `docs/ssot/infrastructure/ssot.audit.hosts.yml` idc02: runner-agent
  notes + newly declared runner-agent.service and kanban-dispatch.service.
- Runbook: `docs/ssot/jobs/kanban/2026-11-24-idc02-vps-ada-pi-lane.yml`.

## How to verify

- `systemctl --user show runner-agent.service -p Environment | grep RUNNER_LABELS`
  on idc02 → contains `vps,push:ada-voice`.
- `git -C ~/CascadeProjects/ada-voice show origin/main:docs/canary/idc02-vps-lane-hv.md`
- Card comms on `idc02-second-ada-pi-lane` + `idc02-vps-lane-canary-hv`.

## Audit note (pre-existing drift, not introduced here)

`scripts/audit-hosts.py --host idc02` is already red on master: the
idc02 census predates the 2026-10-26 capacity move and several later
adds — ~8 undeclared running user services (gpu-queue, ollama,
weaviate, nest-mgr, web, opencode-serve, gesture-relay) and ~10
declared entries whose units are inactive quadlets/oneshots between
fires (audit enumerates `list-units` without `--all`, so dead oneshots
read as "missing"). My two new declarations (runner-agent.service,
kanban-dispatch.service) are the same class — armed, loaded, inactive
between timer/manual fires — correct under declared-or-dead but they
add two more "missing" lines to an already-red audit. Follow-up card
filed: AUD-0035 `idc02-audit-census-reconcile` (backlog).

## Failover usage

Queue an ada-pi/ada-voice dispatch card with `action.labels: [vps]` to
pin idc02, or leave labels off — idc02 now passes the push guard for
ada-voice and competes for unlabeled cards like tony-dell. Caveats:
cap 3 shared with all idc02 dispatch work (not ada-pi-reserved); idc02's
ada-voice checkout is staging — dispatch worktrees are siblings, it
stays clean.

lessons:
  - idc02's kanban-dispatch.service was a linked unit running a stale scripts/-only scaffold (chaba-tony-dell has no docs/ssot) with a dead 127.0.0.1:8787 API default — it only 'worked' because the load gate stopped it first. Check ExecStart provenance before arming labels on a linked unit.
  - runner-agent claim order is priority high>medium>absent>low then oldest updated — and every fleet 'X defers: unclaimable' comms refreshes the card's updated stamp, so a low-priority labeled canary on a busy host starves indefinitely. Queue canaries at priority:high.
  - Multiple Environment=RUNNER_LABELS drop-ins: last file in lexical order wins — name label drop-ins to sort after existing ones (vps-lane.conf > opencode-v2.conf).
