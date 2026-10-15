# Dispatch outcome — tony-dell exec checkout lag (OPS-0479)

## Result: FIXED + verified end-to-end

Chose the card's option B: kept the deliberate two-checkout split and made
the exec checkout pull on kanban-commit's trigger.

## Audit findings

- tony-dell has TWO chaba checkouts by design (ssot.jobs.yml `repo:` map):
  `~/CascadeProjects/chaba-tony-dell` = served/writer (board-api +
  kanban-commit, ~42 units); `~/CascadeProjects/chaba` = job-execution
  (~19 units: flood-alert, chaba-jobs, audits, digests, report-api, …).
- Root cause of the lag: `chaba-repo-sync.timer` (hourly git-safe-pull)
  existed on idc02/idc03/mn01 but was NEVER installed on tony-dell.
  Exec checkout was 84 commits behind origin/master at audit time.

## What changed

Live on tony-dell:
- Installed `chaba-repo-sync.service` + `chaba-repo-sync.timer`
  (canonical files now committed at `systemd/chaba-repo-sync.*`).
- `~/.config/systemd/user/chaba-repo-sync.timer.d/tony-dell-cadence.conf`
  overrides hourly → `OnUnitActiveSec=15min` + `OnBootSec=5min` +
  `RandomizedDelaySec=120` (mirrors kanban-commit.timer's tick).
- `systemd/kanban-commit.service` (repo + live) gained
  `ExecStartPost=-/usr/bin/systemctl --user start --no-block
  chaba-repo-sync.service` — dominant write path propagates in seconds.

Incident found while fixing (bigger than the card):
- `kanban-commit.service` had failed EVERY tick for ~13h (96 exit-1s/24h):
  pre-commit `ssot-optimize-gate` rejected 5 new-debt warnings, and the
  documented baseline-refresh (`ssot-optimize.mjs` full run) crashed on a
  real YAML syntax error in `docs/ssot/jobs/ada/2026-10-15-wp-comment-sync.yml`
  (scalar glued to a flow list). ~133 staged board writes were unpersisted.
- Fixed the YAML, ran the full optimizer, committed the refreshed baseline
  + fix in the served checkout (`1db262c07`), then a manual kanban-commit
  tick committed+pushed the backlog (`ccbc2d351`) and ExecStartPost fired
  chaba-repo-sync — exec checkout converged to origin HEAD within seconds.

Worktree commit (not pushed, per dispatch rails): `d765be9e` —
canonical units, ExecStartPost in `systemd/kanban-commit.service`,
`ssot.audit.hosts.yml` tony-dell expectation entry, AGENTS.md memory
line, trail doc `docs/ssot/jobs/infrastructure/2026-10-16-tony-dell-exec-checkout-sync.yml`.

Follow-ups filed: OPS-0713 (tony-omen lacks the timer). Noted for sweep:
exec-checkout `.local-conflict` residue + one permanently-dirty handoff
file; design question on whether the optimize gate should hard-block the
persistence committer.

## Verify

```
ssh tony-dell 'systemctl --user list-timers chaba-repo-sync.timer;
  journalctl --user -u kanban-commit.service -n5;
  cd ~/CascadeProjects/chaba && git status -sb | head -1'
```
Expect: timer active ~15min cadence, kanban-commit succeeding, exec
checkout `master...origin/master` with no "behind".
