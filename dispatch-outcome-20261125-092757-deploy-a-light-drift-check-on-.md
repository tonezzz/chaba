# Dispatch outcome — scenario-runner-deployed-drift-check

Card: `scenario-runner-deployed-drift-check` (OPS-1160), runner idc02,
worktree `dispatch/20261125-092757-deploy-a-light-drift-check-on-`.

## What changed

- **`scripts/ops/scenario-runner-drift-check.py`** (new, stdlib-only) —
  hourly drift check for the copy-on-install payload of
  `stacks/services/ada-scenario-runner/`. A `PAYLOAD` manifest maps each
  installed file under `~` to its repo-relative source (today one pair:
  `~/.local/share/ada-scenario-runner/scenario-suite-run.sh` ←
  `stacks/services/ada-scenario-runner/scenario-suite-run.sh`). Flags
  `missing`, `not-executable`, `content-drift` (sha256), and
  `reference-missing` (checkout lacks source → check is blind).
  Runtime state in the same dir (`gate-state.json`, `prod-allow-*`
  sentinels) is never compared.
- **`docs/ssot/infrastructure/ssot.jobs.yml`** — job
  `scenario-runner-drift-check`, host idc03, `on_calendar: hourly`,
  `persistent`, `timeout: 2m`.
- **`systemd/generated/idc03/scenario-runner-drift-check.{service,timer}`**
  — rendered units (committed; CI render-drift check stays green).
- **`docs/ssot/infrastructure/ssot.audit.hosts.yml`** — idc03
  `expected_services` census entry for the new timer.
- **`docs/ssot/generated/jobs.*.yml`** — catalog regen; also caught up
  pre-existing manifest drift (ada-memory-merge-proposals,
  ada-morning-brief, ada-transcript-archive on idc03;
  opencode-models-sync on idc02/tony_dell; bank-inspect, queue-mgr on
  tony_dell; `jobs.idc01.yml` newly rendered).
- **`docs/ssot/jobs/infrastructure/2026-11-25-scenario-runner-drift-check.yml`**
  — trail doc (context, changes, alerting design, verification,
  residuals).

## Alerting design

- Channel: board-api `POST /inbox` — deduped focus-inbox entry
  (priority high, tags `ops/monitor/ada-scenario-runner/drift-check`),
  at most once per 6h per condition; recovery silent + journaled; state
  `~/.local/state/scenario-runner-drift-check.json`.
- **Exit 0 on any completed evaluation** per the OPS-0581 exit-code
  contract — findings ride the inbox, not the exit code. The sibling
  watchdogs (`served-checkout-watchdog`, `netdata-nodes-watch`) exit 1
  on alert, which red-flags the timer-sentinel on findings
  (`timer-alert-idc03-served-checkout-watchdog` is the noise example);
  deliberately not copied.
- Inbox text carries the fix: re-run
  `stacks/services/ada-scenario-runner/install.sh` on idc03.

## Deployment on idc03 (verified live)

- Script scp'd to `~/CascadeProjects/chaba/scripts/ops/` — currently
  **untracked** there until the dispatch merge lands; byte-identical
  (sha256 `1035b25a…`) to the committed file, so `git-safe-pull`'s
  untracked-collision resolution (`cmp` → upstream wins) converges
  cleanly on the next chaba-repo-sync pull.
- Rendered units installed to `~/.config/systemd/user/`,
  `daemon-reload` + `enable --now` — timer armed, next fire hourly
  (first scheduled 10:00 +07).
- Live `systemctl --user start` run: `ok — 1 payload file(s) match
  /home/tony/CascadeProjects/chaba`, `status=0/SUCCESS`, state file
  written. Installed wrapper currently matches repo (sha `9f90caa3…`).
- Drift paths verified on idc03 via fake-HOME runs of the deployed
  script: `content-drift` (correct sha pair in message),
  `not-executable`, `missing`, `reference-missing`, and per-condition
  dedupe all fire; rc=0 throughout. No real inbox post was fired
  (avoids noise; the /inbox door itself verified — board-api `/health`
  200 from idc03).

## Repo state

Commit `221a3ef604` on `dispatch/20261125-092757-deploy-a-light-drift-check-on-`
— **not pushed** per dispatch rules; lands via the normal dispatch
close-out/merge, then idc03's chaba-repo-sync picks it up (the running
timer already execs the pre-staged identical file, so there is no
functional gap either way).

## How to verify

- `ssh idc03 'systemctl --user list-timers scenario-runner-drift-check.timer'`
- `ssh idc03 'journalctl --user -u scenario-runner-drift-check.service -n 20'`
- Drift drill (safe): `ssh idc03 'HOME=/tmp/fh python3 ~/CascadeProjects/chaba/scripts/ops/scenario-runner-drift-check.py --repo ~/CascadeProjects/chaba --state /tmp/s.json --no-alert'` after planting a doctored copy under `/tmp/fh/.local/share/ada-scenario-runner/`.
- After merge: `git -C ~/CascadeProjects/chaba log --oneline -3` on idc03 shows the commit; `git status` no longer lists the script as `??`.

lessons:
- Fake-HOME testing changes `Path.home()` for BOTH the installed dir and the default repo path — pass `--repo` explicitly or you test `reference-missing` instead of drift.
- Plain `cp` in test setups can drop the +x bit (umask) — `chmod` after copy or you phantom-flag `not-executable`.
- Sibling watchdogs exit 1 on alert → timer-sentinel red cards on findings; OPS-0581 contract wants exit 0 + a findings channel — don't copy the exit code, copy the dedupe/inbox shape.
- Pre-staging an identical untracked file in a host's exec checkout is safe: git-safe-pull `cmp`s untracked collisions and lets upstream win — byte-identical scp = zero-risk pre-merge deploy.
- `render-jobs-catalog.py` regen surfaces unrelated manifest drift (jobs added without catalog re-render) — commit the whole regenerated set, partial reverts reintroduce drift.
