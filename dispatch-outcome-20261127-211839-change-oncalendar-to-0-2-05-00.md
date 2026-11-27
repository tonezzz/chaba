# Dispatch outcome — runner-tools-converge-timer-2min-bug (OPS-1513)

## What changed
- `ansible/systemd/runner-tools-converge.timer`: `OnCalendar=*:0/2:05` →
  `OnCalendar=0/2:05:00`. The old value parsed as hour=*, minute=0/2,
  second=05 — every 2 minutes fleet-wide (confirmed via
  `systemd-analyze calendar`: normalizes to `*-*-* *:00/2:05`). The new value
  normalizes to `*-*-* 00/2:05:00` — every 2 hours at :05:00, matching the
  unit Description and commit 45219a493cc's intent.
- New evidence file:
  `docs/ssot/jobs/infrastructure/2026-11-27-runner-tools-converge-timer-2min-fix.yml`

## What was run
1. `ansible-playbook playbooks/install-runner-tools-converge.yml --check --diff
   --limit 'tony-dell:tony-omen:idc02:idc03:con01:tony-macbook:mn01'` — all 7
   hosts reachable, only the expected timer-line diff (con01 also showed its
   installed converge script was stale vs master).
2. Same playbook without `--check` — applied: 7/7 ok, 0 unreachable, 0
   failed. changed=1 per host (timer); con01 changed=2 (timer + script sync
   to the committed master version).
3. Idempotency re-check `--check --diff` — changed=0 on all 7 hosts.

## Verification
- `systemctl --machine=tony@.host --user list-timers
  runner-tools-converge.timer` on all 7 hosts: NEXT = Fri 2026-11-27 22:05:00
  +07 (~38 min out), LAST ~21:24 under the old cadence. daemon-reload
  rescheduled the live timers; no restart needed.
- Note: plain `systemctl --user` fails over ansible ad-hoc (become=True →
  root, no user bus); the `--machine=tony@.host --user` form works, and
  tony-macbook needs `-e ansible_become=false` (no passwordless sudo).

## How to verify
- Repo: `git show HEAD -- ansible/systemd/runner-tools-converge.timer`
- Live: `ssh <host> 'systemctl --machine=tony@.host --user list-timers
  runner-tools-converge.timer'` — NEXT should stay on even-hour :05:00.
- Journal quiet check: `journalctl --user -u runner-tools-converge.service`
  should show ~2h spacing, not 2-min spacing.

lessons:
- systemd OnCalendar `H:M:S` parses as Hour:Minute:Second — `*:0/2:05` steps
  the minute field (every 2 min), not the hour. Run `systemd-analyze calendar`
  before committing timer changes.
- `ansible -m shell -a 'systemctl --user ...'` runs as root via ansible.cfg
  become=True and loses the user bus; use
  `systemctl --machine=<user>@.host --user` for timer reads.
- daemon-reload alone reschedules active timers after a unit-file change —
  no explicit timer restart needed.
