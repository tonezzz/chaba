# Dispatch outcome — chaba-board-quadlet (package board-api + render + kanban-sync as one quadlet on idc03)

## What changed

New stack `stacks/idc03/chaba-board/` packaging the whole board stack as
podman quadlets on one image (`localhost/chaba-board:latest`,
python:3.12-slim + pyyaml + git + openssh-client):

- `chaba-board-api.container` — board-api daemon, Network=host keeps
  127.0.0.1:8787 and all loopback writers unchanged, Restart=always,
  /health probe.
- `chaba-board-render.{container,timer}` — 60s render sweep
  (board-render-guard.py).
- `chaba-board-sync.{container,timer}` — 15-min kanban-sync CMS xmatch,
  Persistent, OnFailure -> ada-report-fail preserved.
- `chaba-board-commit.{container,timer}` — 15-min kanban-commit git
  persistence, RandomizedDelaySec=120 stagger preserved.
- `run-{api,sync,commit}.sh` entrypoints (installed to
  `~/.config/containers/chaba-board/` by install.sh).
- `Containerfile`, `install.sh` (with `--cutover`), `stack.yml`.
- Job trail: `docs/ssot/jobs/board/2026-11-24-board-quadlet-packaging.yml`.

## Key design decisions

- **One quadlet stack, not a literal single .container**: systemd timers
  can't live inside a container; in-container cron would fork the
  kanban-sync schedule away from `ssot.jobs.yml` (render-jobs.py is the
  schedule source of truth). 4 units share ONE image — that is the
  packaging unit.
- **Volume=/home/tony + /tmp**: identical paths keep board-api's
  `__file__`-derived REPO, the chaba-kanban-sync worktree, ~/.ssh and
  ~/.config/secrets working; the /tmp mount keeps the
  `/tmp/board-api*.lock` flock domain shared with host-side writers
  (kanban-dispatch, merge-sweep, git-safe-pull) — without it card-YAML
  lock races return.
- **Network=host** everywhere: zero changes for Caddy upstreams and
  loopback callers.

## Known deltas at cutover (documented in stack.yml + job doc)

1. kanban-commit's ExecStartPost kick of chaba-repo-sync.service can't
   reach host systemd — covered by the 15-min chaba-repo-sync.timer.
2. kanban-commit.sh's post-pull `try-restart chaba-board-api.service`
   is a no-op in-container; API picks up pulled code on next restart.
3. `ssot.jobs.yml` still declares `kanban-sync` dispatch:systemd —
   retire/annotate at cutover or render-jobs.py --install recreates the
   host units.

## Result / status

**Packaged, NOT deployed.** Nothing was installed on idc03 — dispatch
rules forbid deploy without explicit approval, and this is the
production write path. Cutover is one command on idc03 after merge:
`bash stacks/idc03/chaba-board/install.sh --cutover` (full runbook in
the job doc).

## How to verify

- `bash -n stacks/idc03/chaba-board/*.sh` — pass
- `python3 -c "import yaml; yaml.safe_load(open('stacks/idc03/chaba-board/stack.yml'))"` — pass
- On idc03 post-merge: `bash stacks/idc03/chaba-board/install.sh`,
  inspect `systemctl --user list-timers 'chaba-board-*'`, then
  `--cutover` and `curl -sf http://127.0.0.1:8787/health`.

lessons:
- Quadlet .timer files pair with a same-named .container's generated .service — oneshot cadence jobs = .container+.timer pairs, not timers inside the container.
- Podman quadlet `print`/`list` only resolve quadlets already in ~/.config/containers/systemd — can't dry-run arbitrary paths without touching host config.
- board-api derives REPO from `__file__`, so bind-mounting the checkout at its real path (/home/tony/CascadeProjects/chaba-tony-dell) keeps every path assumption intact; mounting all of $HOME + /tmp is the low-risk packaging move for this stack.
- /tmp/board-api*.lock is a cross-process flock domain shared with host-side writers — any containerization MUST bind-mount host /tmp or the card-YAML lock splits.
- kanban-sync's schedule is owned by ssot.jobs.yml via render-jobs.py — containerizing the unit without retiring the job entry lets a future --install recreate the host units.
