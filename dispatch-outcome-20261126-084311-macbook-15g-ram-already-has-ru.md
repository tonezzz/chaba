# Dispatch outcome — tony-macbook-daytime-runner (attempt 2, 2026-11-26, idc02)

Card: `tony-macbook-daytime-runner` (OPS-0059).

## What this attempt fixed

Attempt 1 (ran ON tony-macbook) completed the host work and pushed
`dispatch/20261125-190949-...` (commit `00b8fe74`), but the merge was held:
the dispatch test gate found no pytest on tony-macbook (OPS-1191) and the
worktree tripped the >10-commit single-writer checkpoint warning. This
attempt ran on **idc02** (pytest-capable), fast-forwarded to current master,
and **cherry-picked `00b8fe74` → `4c3927ccd7` with zero conflicts**. All 10
files landed: `scripts/ops/macbook-day-awake.{sh,desktop}`,
`scripts/ops/lid-blank-watch.sh`, `systemd/{macbook-day-awake,lid-blank-watch}.service`,
SSOT mirrors, job doc, prior outcome doc.

## Verified live on tony-macbook (ssh from idc02)

- `runner-agent.timer` firing ~2 min cadence; unit env
  `RUNNER_LABELS=macbook,local-8c,always-home RUNNER_CAP=4
  RUNNER_MAX_LOAD_PC=1.0` — exactly matches `ssot.kanban.yml` (cherry-pick
  content is accurate, not stale).
- `~/.local/bin/macbook-day-awake.sh` + `~/.config/autostart/
  macbook-day-awake.desktop` still installed from attempt 1.
- **No inhibitor currently held** (`systemd-inhibit --list`): the running
  xfce4-session (CRD session-c1, pid 2896) started Nov 25 09:38 — ~11 h
  *before* the .desktop was installed (20:31) — so autostart never fired for
  it. It arms at next graphical login.
- **Polkit rule still absent.** Tony answered "proceed" on request
  `day-awake-inhibit-deployed-via-xfce-auto-544ad5`, but the step needs an
  interactive sudo password — `sudo -n` fails, no NOPASSWD covers file
  install, `/etc/polkit-1/rules.d` is `root:polkitd 750`. An agent cannot
  execute it unattended.
- Exhausted unprivileged in-session exec channels: the session bus is the
  shared *user* bus (dbus-daemon in `user@1000.service`, not
  `session-c1.scope`) so dbus activation lands session-less → denied;
  xfce4-session's D-Bus API has no exec method; X display `:20` has no
  usable windows; `session-c1.scope/cgroup.procs` is root-owned.

## Risk assessment (corrected)

Current suspend exposure is **low**: the XFCE/CRD session has *no*
idle-suspend mechanism at all (xfce4-power-manager not installed, no GNOME
power daemon in-session, no logind `IdleAction`). Only battery lid-close
(suspend-then-hibernate — which the script releases inhibit for by design,
bag safety) and manual suspend remain. The inhibitor's real value is in
*future* sessions — a local/GNOME login gets `sleep-inactive-battery-type=
suspend` — and the autostart covers every graphical login.

## Changes in this branch (on top of cherry-pick `4c3927ccd7`)

- `docs/ssot/ssot.mysystem.macbook.yml` — corrected stale "lid close no
  longer suspends" line: `hibernate.conf` overrides `headless-crd.conf`,
  so battery lid-close → suspend-then-hibernate (SYS-1410 cold-boot).
- `docs/ssot/jobs/infrastructure/2026-11-25-macbook-daytime-runner.yml` —
  appended `attempt_2_2026_11_26` block with verification + residual.
- This outcome file.

## Result / how to verify

- Branch `dispatch/20261126-084311-macbook-15g-ram-already-has-ru` carries
  the full deliverable; merge lands it via the normal dispatch pipeline
  (pytest present on idc02).
- On tony-macbook: `systemd-inhibit --list | grep 'daytime runner'` shows a
  `block` entry on `sleep,idle` during 07:00–23:00 once any graphical
  session (re)starts.
- Optional session-independent coverage still needs one interactive sudo
  (re-requested on the card): install
  `/etc/polkit-1/rules.d/50-macbook-day-awake.rules` then
  `systemctl --user enable --now macbook-day-awake.service`. Assessed
  optional — autostart covers the sessions that can actually idle-suspend.

lessons:
- Dispatch test gate is per-host: tony-macbook has no pytest so merges routed
  there hold closed (OPS-1191); a pytest-capable runner (idc02) lands the
  same branch fine — route repo-change cards away from macbook.
- logind block inhibitors need a process inside an ACTIVE logind session
  cgroup — the shared user bus (`--address=systemd:` dbus-daemon under
  user@1000.service) activates services session-less, so dbus-activation is
  NOT an in-session exec channel on dbus-user-session distros.
- XFCE session D-Bus APIs expose lifecycle only (org.xfce.Session.Manager:
  Logout/Shutdown/Checkpoint) — no exec; X display may have zero usable
  windows making XTEST injection impossible too.
- Card answers like "proceed" on a sudo-gated request can't be executed by
  an unattended agent — re-raise the request naming the interactive step
  rather than silently dropping it.
- Suspend-exposure claims age fast: the XFCE/CRD session has no
  idle-suspend mechanism at all, so "keep it awake" risk is mostly
  future-session + lid-close — verify which DE/power-daemon actually runs
  before scoping inhibit work.
