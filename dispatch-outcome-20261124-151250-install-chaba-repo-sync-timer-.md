# Dispatch outcome: install chaba-repo-sync.timer on tony-omen

## Result: DONE (verified)

The `chaba-repo-sync.timer` / `chaba-repo-sync.service` pair was already
installed on tony-omen (`~/.config/systemd/user/`), enabled, and firing
hourly — the done-condition (`systemctl --user status chaba-repo-sync.timer`
shows active) was already met. Installed unit files had drifted from the repo
versions only in `Description=` strings; all functional fields
(`OnCalendar=hourly`, `Persistent=true`, `ExecStart=git-safe-pull.sh`) were
identical.

Actions taken:
- Copied `systemd/chaba-repo-sync.{service,timer}` from the repo (md5
  29afc573… / 4f2349f7…, identical in this worktree and in
  tony-omen's `~/CascadeProjects/chaba/systemd/`) over
  `tony-omen:~/.config/systemd/user/`.
- Ran `systemctl --user daemon-reload` and `systemctl --user enable --now
  chaba-repo-sync.timer` on tony-omen.

Verification:
- `systemctl --user status chaba-repo-sync.timer` → `Active: active (waiting)`,
  `Loaded: enabled`, next trigger Tue 2026-11-24 16:00 +07.
- `chaba-repo-sync.service` last ran 15:00 +07 today, exited
  `status=0/SUCCESS` (TriggeredBy the timer).
- `~/CascadeProjects/chaba` on tony-omen is the job-exec checkout kept current
  by this timer — repo drift is now covered.

## How to verify

```
ssh tony-omen 'systemctl --user status chaba-repo-sync.timer'
ssh tony-omen 'systemctl --user list-timers chaba-repo-sync.timer'
```

## Lessons

- chaba-repo-sync.timer was already installed and healthy on tony-omen — the
  card's premise (missing timer) was stale; verify real state before assuming
  the install is needed.
- Installed unit files drifted from repo only in Description text; syncing
  them is harmless but changes nothing functional — check `diff` before
  treating unit-file drift as a problem.
