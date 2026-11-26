# Dispatch outcome — ops-mn01-restore-sshd-shell-20261126

## What was done

Host-local fix on mn01 (no repo work, no git push, per card spec). Removed the
`ForceCommand internal-sftp` directive that had been added to
`/etc/ssh/sshd_config` line 80 on 2026-11-26 08:25, which was blocking all
shell/Ansible SSH access.

Ran the prescribed sequence verbatim with `sudo -n`:

1. `cp -a /etc/ssh/sshd_config /etc/ssh/sshd_config.bak-20261126-sftp-only` — backup taken
2. `sed -i 's|^ForceCommand internal-sftp$|# SFTP-only restriction removed 2026-11-26 — restore host standard shell access|'` — directive commented out in place
3. `sshd -t` → `SSHD_T_OK` (config valid)
4. `systemctl restart ssh` → `SSH_RESTARTED`
5. Final grep produced no output (the pattern used BRE, so `|` was literal — see lessons)

## Verification

- `grep -nE 'ForceCommand|SFTP-only' /etc/ssh/sshd_config` → only line 80, now the removal comment; no `ForceCommand` directive remains.
- `sudo -n sshd -T | grep -i forcecommand` → `forcecommand none` (effective config confirms shell access).
- `systemctl is-active ssh` → `active`.
- Backup file present: `/etc/ssh/sshd_config.bak-20261126-sftp-only` (root:root, 1798 bytes, preserves 08:25 timestamp via `cp -a`).
- Pre-check confirmed no `ForceCommand` in `/etc/ssh/sshd_config.d/` drop-ins (only `00-no-password.conf` present).

## Result

Standard SSH shell access restored on mn01. Verbatim command output and
verification evidence posted as a comment on card
`ops-mn01-restore-sshd-shell-20261126` via board-api. No other files or
services were changed; no git repo was edited or pushed.

## How to verify

- `ssh tony@mn01 'echo ok'` (or any shell/Ansible probe) should now return a shell instead of an SFTP-only session.
- `sudo sshd -T | grep forcecommand` on mn01 → `forcecommand none`.
- Rollback if ever needed: `sudo cp -a /etc/ssh/sshd_config.bak-20261126-sftp-only /etc/ssh/sshd_config && sudo systemctl restart ssh`.

## Lessons

- Card-specified verification `grep 'ForceCommand|SFTP-only'` used BRE, so the `|` was literal and it could never match — a silent no-op check. Re-run with `grep -E` (or `grep -e A -e B`) when a card's verify step pipes alternation without `-E`.
- `sshd -T` (effective config dump) is the strongest proof that a `ForceCommand`/`Match` restriction is actually gone — it resolves includes, drop-ins, and first-match-wins semantics that raw file greps miss.
- `systemctl restart ssh` (not `sshd`) is the correct unit name on this Ubuntu host; existing sessions are unaffected, so the restart is safe even while connected.
