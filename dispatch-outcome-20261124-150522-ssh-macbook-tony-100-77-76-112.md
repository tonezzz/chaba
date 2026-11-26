# Dispatch outcome — tony-macbook-restore-enroll (2026-11-24)

## Result: partial — runner-agent verified live; KK-files restore blocked on missing backup media

Card: `tony-macbook-restore-enroll` (SYS-0452). Spec: ssh tony@100.77.76.112,
(1) rsync KK files from the macOS backup into ~, (2) install/verify the
runner-agent lane (cap 2, cpu/dev/portable), (3) verify claims/capacity.

## What was found and done

### SSH access — was broken, now repaired

- `ssh macbook` from omen and dell returned `Permission denied (publickey)`.
  The macbook's `~/.ssh/authorized_keys` had been rebuilt to 3 keys — the
  rejoin-seeded dedicated keys (omen `id_ed25519_macbook`, both dell keys)
  were gone. ssh-mesh-sync only appends *default* keys, so the alias keys
  never returned.
- Fix: re-added omen `id_ed25519_macbook.pub` and dell `id_cascade.pub` to
  the macbook's authorized_keys, ran `scripts/ops/ssh-mesh-sync.sh`
  (7 hosts synced, 42 key-checks; idc01 unreachable — pre-existing), and
  added the missing `Host macbook tony-macbook` stanza to mn01's
  `~/.ssh/config` (its `id_cascade` key was already authorized; bare ssh
  had no default identity to offer).
- Verified: `ssh macbook` works from omen and dell; mn01, idc02, idc03 all
  reach tony-macbook. authorized_keys now carries 9 fleet keys.

### Runner-agent lane — already enrolled, verified converged

- Installed `~/.local/bin/runner-agent` sha256 == repo copy ==
  `origin/master` (`52cbc072…`, commit 0c451dd4). The 08:40 drift defer
  healed via `_self_update`/sync-runner-tools — no redeploy needed.
- `runner-agent.service`+`.timer` active and firing; unit env:
  `RUNNER_CAP=3`, `RUNNER_MAX_LOAD_PC=0.8`,
  `RUNNER_LABELS=macbook,local-8c,always-home` — matches
  `ssot.kanban.yml runner_fleet` (cap was raised 2→3 today via card
  `tony-macbook-cap-raise`; spec's "cap 2" is superseded).
- Live proof of claims: `/host-status?host=tony-macbook` showed 3 active
  cards at 15:13; merge-sweep merged a dispatch branch *from* tony-macbook
  at 15:23. Fleet inventory already lists it: `ssot.host-roles.yml`,
  `ssot.kanban.yml runner_fleet`, `audit-hosts.py` HOSTS,
  `ssot.host-capacity.yml`.
- Refreshed stale fields in `ssot.host-capacity.yml` (`tony_macbook`:
  disk free 203→96 GB, runner note cap2/cpu,dev,portable →
  cap3/macbook,local-8c,always-home).

### KK files — BLOCKED, board request raised

- Backup per the rejoin job record: `home/tony/macbook-backup-2026-10-10`
  on the **ubuntu-usb stick** (117G portable Ubuntu) — 23G kkkakk home +
  211M Shared. The stick is attached to **no reachable host**: lsblk/lsusb
  on the macbook show no mass-storage (only the USB LAN dongle + an
  iPhone in recovery mode); dell/omen/mn01/idc02/idc03 have no ~117G USB
  device; kk-mac `diskutil` shows no external disk; `/mnt/ubuntu-usb` on
  dell is an empty mountpoint.
- No copy exists on the macbook's disk (du/find clean — largest dirs are
  CascadeProjects 30G, .config 30G) and restic only covers config dirs.
- Raised board request `kk-files-restore-is-blocked-on-the-backu-27b870`:
  asks Tony to plug in the stick and confirm restore scope (recommended:
  rsync preserving the backup's top-level structure into ~, never
  overwriting; alternatives: merge-into-~ which would clobber .ssh/.config,
  or user-dirs-only).

### Skipped per spec

- redis — no backup exists (podman redis-data volume never exported).

## Files changed in this worktree

- `docs/ssot/infrastructure/ssot.host-capacity.yml` — tony_macbook disk
  free + runner-lane note refreshed to live state.
- `docs/ssot/jobs/infrastructure/2026-11-24-tony-macbook-ssh-mesh-restore-enroll.yml`
  — job trail (ssh repair, runner verification, blocker detail).

Off-repo changes (fleet hosts): macbook authorized_keys (+omen
id_ed25519_macbook, +dell id_cascade, +mesh-converged defaults), mn01
`~/.ssh/config` (+Host macbook stanza).

## How to verify

- `ssh macbook hostname` from omen and dell → `tony-macbook`.
- `ssh macbook 'sha256sum ~/.local/bin/runner-agent
  ~/CascadeProjects/chaba/scripts/board/runner-agent.py'` → identical,
  and `git show origin/master:scripts/board/runner-agent.py | sha256sum`
  matches.
- `ssh macbook 'systemctl --user status runner-agent.timer'` → active.
- `curl -s 'https://idc03.taila0626a.ts.net:10000/host-status?host=tony-macbook'`
  → live claims under `processing`.
- KK files: pending Tony plugging in the ubuntu-usb stick (board request
  on the card).

lessons:
- Dedicated per-host ssh alias keys are NOT covered by ssh-mesh-sync (it only converges each host's default id_ed25519/id_cascade) — when authorized_keys is rebuilt, alias keys like id_ed25519_macbook must be re-seeded by hand or `ssh macbook` dies while bare-IP mesh still works.
- `ssh <host> 'ssh <target> ...'` nested via a working jump host (idc02) is a reliable fallback when your own key is denied — idc02's default key was still authorized.
- runner-agent drift defers self-heal via _self_update/sync-runner-tools once the repo checkout is current — check sha256 of installed vs repo vs `git show origin/master:` before assuming a manual scp is needed.
- Card specs age: this card said "cap 2, labels cpu/dev/portable" but the fleet had already moved to cap 3 / macbook,local-8c,always-home via tony-macbook-cap-raise — verify live unit env + ssot.kanban.yml runner_fleet before "installing" anything.
- Physical-media dependencies (USB stick backups) can't be verified remotely — lsblk/lsusb on every fleet host + the target before declaring a restore blocked.
