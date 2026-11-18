# Dispatch outcome — runner-tooling-drift-recurs-installed-ru-3aad1e

## What the card asked
Installed copies under `~/.local/bin` are snapshots; nothing synced them when
`scripts/board/runner-agent.py` / `scripts/devin/devin-dispatch.sh` changed on
master. Drift was detect-only (runner-fleet-health inside kanban-sync). Card
recommended option (a): self-healing sync, plus a `dispatch_repos.conf` drift
audit in the same pass.

## What changed (branch `dispatch/20261118-202035-evidence-2026-11-18-dispatch-d`)

- **NEW `scripts/devin/sync-runner-tools.sh`** — converges the snapshot set:
  `runner-agent.py`→`~/.local/bin/runner-agent`,
  `devin-dispatch.sh`→`~/.local/bin/devin-dispatch`,
  `claude-dispatch.sh`, `devin-dispatch-prune.sh`, `dispatch-queue.sh`, and
  `dispatch_repos.py` (update-only — when present in `~/.local/bin` it shadows
  the checkout in `dr_module()`).
  Rules: byte-compare; missing dest installs only for runner-agent/devin-dispatch
  and only with provisioning evidence (systemd user unit, LaunchAgent,
  `~/.local/share/runner-agent`, `DISPATCH_DIR`); a differing dest that is
  NEWER-mtime is kept with a warning (never-downgrade, same guard as
  `_self_update()`); dirty-or-unparseable sources are skipped. `repos.conf` is
  audited (name/branch set vs canonical) and reported — never overwritten,
  per-host tables are legal (kk-mac ships chaba-only).
- **`scripts/git-safe-pull.sh`** — tail step invokes the sync via `nf()` on every
  run (post-pull and no-op ticks), so `chaba-repo-sync.timer`, idc03's
  kanban-commit `ExecStartPost`, and satellite `git-safe-push` all converge
  tooling within one sync cycle. Guarded to canonical checkouts
  (`~/CascadeProjects/chaba{,-tony-dell}`) so dispatch worktrees can't poison
  `~/.local/bin`; `SYNC_RUNNER_TOOLS=0` opts out.
- **`scripts/board/runner-fleet-health.py`** — REMOTE_PROBE now captures
  `$DISPATCH_DIR/repos.conf` (exists/sha/name→branch); `judge()` notes row-set
  drift vs canonical `scripts/devin/dispatch-repos.conf` and a missing conf on a
  host with devin-dispatch installed. HELP for runner-agent/devin-dispatch now
  leads with the self-heal path.
- **`scripts/board/runner-agent.py`** — `_self_update()` docstring updated to
  name the fleet-level mechanism.
- **`systemd/chaba-repo-sync.service`** — Description updated.
- **`docs/ssot/infrastructure/ssot.jobs.yml`** — kanban-sync note records the
  self-heal + repos.conf audit.
- **NEW `docs/ssot/jobs/infrastructure/2026-11-18-runner-tooling-selfheal-sync.yml`**
  — runbook: topology, verify, rollback.

## Verified
- `bash -n` both scripts; `compile()` both edited py files; yaml parse both yml.
- Sandboxed HOME inside the worktree, all 7 scenarios pass: unprovisioned host
  installs nothing; provisioned host installs missing runner-agent+devin-dispatch;
  older drifted dest refreshes; newer-mtime dest is kept+warned; leaf tools
  update-if-present only; repos.conf diff reported without rewrite; non-canonical
  path (worktree) skipped.
- Live REMOTE_PROBE on idc02: emitted `repos_conf` correctly — and surfaced a
  real finding: **idc02 has devin-dispatch but NO repos.conf** (builtin table in
  use, itself a drifting snapshot). Now a standing audit note.
- `pytest tests/board` — 626 passed.

## Done-criteria mapping
"installed hash == repo hash on all runner hosts without manual intervention,
or drift auto-files a card within one sync cycle": after merge, each host's next
git-safe-pull tick (≤2 ticks worst case, hourly/15min cadence) refreshes drifted
snapshots; residual drift (newer dest, unprovisioned) stays carded via
runner-fleet-health → `runner-auto-<host>`.

## Not done / caveats
- No host touched from this worktree (rails). Convergence lands on merge+pull.
- If a host's `chaba-repo-sync.timer` is itself broken, drift persists — but that
  already cards via timer-alert/runner-auto surfaces.
