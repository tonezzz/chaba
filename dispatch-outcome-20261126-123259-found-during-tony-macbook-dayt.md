# Dispatch outcome — tony-macbook-hibernate-resume-broken-eve-8ac607

**Card:** tony-macbook-hibernate-resume-broken-eve-8ac607 (SYS-1410)
**Date:** 2026-11-26 · **Host:** tony-dell (worktree) + on-host read-only via `ssh macbook`
**Result:** diagnosed on-host, fix staged, **application blocked on Tony's sudo** — board request `hibernate-fix-option` raised with options (a recommended).

## What was found (verified live on tony-macbook)

- SSH to tony-macbook works — the primer's "SSH broken fleet-wide" pitfall is stale.
- Kernel 7.0.0-44-generic, systemd 259.9. Power config: `logind.conf.d/headless-crd.conf` (lid ignore on AC) overridden for `HandleLidSwitch` by `hibernate.conf` → `suspend-then-hibernate`; `sleep.conf.d/hibernate.conf` sets `HibernateMode=shutdown`, `HibernateDelaySec=7200`.
- Resume plumbing is present and correct-looking: cmdline `resume=PARTUUID=cf9d881c-… resume_offset=29630464`, `/sys/power/resume=259:2`, `/sys/power/state` includes `disk`.
- **Every** suspend→hibernate cycle cold-boots: journal boot boundaries show 13s/9s/~65s gaps bracketed by `systemd-hibernate-resume: Unable to resume … offset 29630464` → kernel `PM: Image not found (code -22)` → normal boot (11-21, 11-23 ×2, 11-25).
- Likely root cause: `/swap.img` is **fragmented** — kernel swap-on line: `extents:22 across:23609340k` for a 19.9G file. The kernel resume path gets a single `resume_offset` (file start) and cannot locate the image in a non-contiguous swapfile — the known "Image not found" failure mode. Prior interactive fix attempts (`/tmp/enable-hibernate.sh`, `fix-hibernate.sh`, `fix-hibernate2.sh`, ~Oct 20, visible in `~/.bash_history`) did not converge.
- s2idle suspend itself verified working: `PM: suspend entry (s2idle)` 11-26 11:36 → `suspend exit` 12:16, clean.
- Red herring checked: `busctl CanHibernate` returns `"no"` — in systemd v259 source this is a **polkit** answer for the SSH caller, not a capability report.
- No agent-usable apply path: `sudo -n` fails; NOPASSWD covers only apt-get update/upgrade (specific pkgs), brcmfmac modprobe, nmcli wifi, reboot. No polkit rule installed yet.

## What changed (commit f840c62ea06 on dispatch branch)

- `scripts/ops/macbook-disable-hibernate.sh` — new idempotent script (option a): backs up `hibernate.conf`, rewrites `HandleLidSwitch=suspend-then-hibernate` → `suspend`, restarts `systemd-logind`, prints effective config. Revert = restore `.bak-*` + restart logind. Also copied to `tony-macbook:~/macbook-disable-hibernate.sh` so it's runnable immediately.
- `docs/ssot/ssot.mysystem.macbook.yml` — Power & Sleep section documents diagnosis + pending fix.
- `docs/ssot/jobs/infrastructure/2026-11-26-macbook-hibernate-resume-disable.yml` — full job trail with evidence and option-(b) runbook notes.

## Decision requested (board request `hibernate-fix-option`)

- **(a) ★ recommended** — `ssh macbook && sudo bash ~/macbook-disable-hibernate.sh`: battery lid-close becomes reliable s2idle suspend; AC lid-close stays ignored; bag safety preserved. Reversible in one command.
- (b) debug resume: recreate `/swap.img` contiguously (dd), recompute `resume_offset`, update-grub + initramfs, reboot, test-hibernate — multi-step sudo on the runner, may still hit Polaris11/amdgpu resume issues.
- (c) keep suspend-then-hibernate, other approach.

## How to verify after Tony runs it

- `ssh macbook 'systemd-analyze cat-config systemd/logind.conf | grep HandleLidSwitch'` → last entry `HandleLidSwitch=suspend`
- Next battery lid-close: `journalctl -k -b | grep 'PM: '` → `suspend entry`/`suspend exit` pair, no hibernate, host resumes instead of cold-booting.
- Card comms + request carry the same instructions.

## Notes

- Until applied, every battery lid-close remains a hibernate→cold-boot fleet-offline event; `macbook-day-awake` inhibit only reduces exposure (and its session-independent variant still awaits the same class of sudo — could be done in the same sudo session).
- `systemctl hibernate` on this host remains broken-resume — do not use manually.

lessons:
- logind CanHibernate "no" over SSH is a polkit answer (needs active session), not a capability report — check systemd source before treating it as "hibernation unsupported".
- Kernel "PM: Image not found (code -22)" on resume = image header unreadable at resume_offset — first suspect a fragmented swapfile ("extents:N" in the swap-on kernel line); fallocate-created swapfiles fragment easily.
- tony-macbook sudo is password-only except a small NOPASSWD list — any /etc change needs a board request for one interactive sudo (same pattern as the day-awake polkit rule).
- journalctl --list-boots gaps of seconds-to-a-minute bracketed by systemd-hibernate-resume failure = failed-resume cold boot signature; multi-day uptimes mean no hibernate occurred.
- ~/.bash_history on the target host reveals prior manual fix attempts (/tmp/fix-*.sh) — read it before re-debugging; option (b) was already tried interactively and did not converge.
