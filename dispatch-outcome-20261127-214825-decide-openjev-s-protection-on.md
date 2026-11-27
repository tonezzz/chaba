# Dispatch outcome — openjev-idc02-earlyoom-exposure (OPS-1517)

## Decision: (c) ACCEPT — no config change

openjev on idc02 stays earlyoom-eligible **by design**. Verified live over
ansible (read-only) rather than from the card brief:

- `open-jev.service` (user unit, idc02 `~/.config/systemd/user/open-jev.service`,
  no drop-ins) already carries `MemoryMax=12G`, `MemorySwapMax=2G`,
  `Restart=always`, `OOMScoreAdjust=200` — option (b) is already satisfied,
  and cgroup caps don't influence earlyoom's `oom_score`-based victim
  selection anyway.
- openjev IS the top badness candidate (comm=`openjev`, RSS ~2.95 GiB,
  oom_score=920) and earlyoom has already killed it twice in 14 days —
  but `Restart=always` self-heals: SIGTERM 17:59:15 today → unit active
  17:59:39 (~24s; NRestarts=2 matches both journal kills). Unlike OPS-1516's
  jev (`Restart=on-failure` + SIGTERM clean exit → silent 17-min outage),
  there is no silent-death failure mode here.
- The lane is redundant (tony-omen serves the same gemma-3-4b-it
  /v1/systemone on :8777) and degrades gracefully (JEV_LANE classify falls
  back to the devin lane). `/health` on :8777 returned 200 at decision time.
- Option (a) rejected per the mn01 precedent
  (`2026-11-25-mn01-mn-ha-dev-earlyoom-kills.yml`, `do_not` list): on a
  zero-swap host `--avoid` relocates kills, not prevents them. Exempting
  the single largest process forces earlyoom to kill more, smaller victims
  per event — idc02's 2026-11-27 20:34–20:49 storm already killed mddbd x4,
  chrome x4, jev, and two ~4.3 GiB python procs.

## Root cause surfaced

idc02 is chronically oversubscribed: ~11.8/16 GiB used steady-state, **zero
swap** → earlyoom's swap arm is permanently true → 15 SIGTERMs in 14 days.
The durable fix is zram swap (fleet-standard `zram-swap.service` pattern,
`ansible/playbooks/zram-swap.yml` needs an idc02-sized variant), which helps
every service, not just openjev. Filed as card **OPS-1519
`idc02-zram-swap-earlyoom-relief`** (backlog).

## Deliverables

- Decision/evidence doc:
  `docs/ssot/jobs/infrastructure/2026-11-27-idc02-openjev-earlyoom-decision.yml`
- Card comms posted on `openjev-idc02-earlyoom-exposure` with the verdict.
- Follow-up card `idc02-zram-swap-earlyoom-relief` (OPS-1519) created via
  board-api.

## How to verify

- `ssh/ansible idc02 'journalctl -u earlyoom.service --since "14 days ago"'`
  — openjev SIGTERMs at Nov 25 14:38 and Nov 27 17:59; unit
  `ActiveEnterTimestamp` 17:59:39 same day.
- `systemctl --machine=tony@.host --user show open-jev.service -p
  MemoryMax,Restart,NRestarts` on idc02 → 12G / always / 2.
- `cat /etc/default/earlyoom` on idc02 → still only
  `--avoid '(^|/)(jev)$'` (unchanged, as decided).

lessons:
- On zero-swap hosts, earlyoom `--avoid` relocates kills rather than
  preventing them — exempting the largest process maximizes collateral;
  fix with zram/headroom, not victim lists (mn01 precedent confirmed).
- `Restart=always` vs `on-failure` is the real earlyoom-kill severity
  differentiator: SIGTERM exits are "clean" to systemd but `always` still
  restarts — check Restart policy before assuming a silent outage.
- ansible ad-hoc `command` doesn't interpret pipes/`;` — use `-m shell`;
  `systemctl cat` doesn't work via `--machine=` — read unit files directly.
- earlyoom reads `/proc/*/oom_score`; cgroup MemoryMax does NOT protect a
  process from earlyoom (separate kernel/cgroup OOM path only).
