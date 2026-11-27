# Dispatch outcome — idc02-zram-swap-earlyoom-relief (OPS-1519)

## Result: DONE — zram swap deployed and verified on idc02

idc02 (16 GiB, was ZERO swap) now runs the fleet-standard compressed-swap
stack: `/dev/zram0` 8 GiB, zstd, 4 streams, swapon priority 100,
`zram-swap.service` enabled+active. earlyoom's swap arm is no longer
permanently true — it now requires >10% of 8 GiB swap in use before the
swap leg can fire.

## What changed

- **New playbook** `ansible/playbooks/zram-swap-deploy.yml` — self-contained
  (content: blocks, no template files). Installs the fleet-standard stack
  (`/etc/systemd/system/zram-swap.service` + `.d/retry.conf` drop-in +
  `/usr/local/bin/zram-swap-{setup,teardown}.sh`) on any host opting in via
  the `zram_size` inventory var. Handles the kernel-module gap:
  `modinfo zram` probe → `apt install linux-modules-extra-{{kernel}}` on
  Ubuntu → `modprobe` → deploy → enable --now → swapon/free report.
- **`ansible/inventory/hosts.yml`** — `zram_size: 8G` added under
  `vps:idc02` (defaults: zstd, 4 streams).
- **`docs/ssot/infrastructure/ssot.audit.hosts.yml`** — `zram-swap.service`
  declared in idc02 `expected_services` so audit-hosts verifies it.
- **Job doc** `docs/ssot/jobs/infrastructure/2026-11-27-idc02-zram-swap.yml`
  — full evidence, rollback, follow-ups.

## How it was applied

Ran from idc02 itself (ansible controller) via a staged copy of the
playbook in `/tmp/zram-deploy/` with a localhost inventory — the playbook
is self-contained so no repo checkout was needed. `--check --diff`
preflight clean (0 unreachable/0 failed), real run `ok=13 changed=7
failed=0`, second `--check` `changed=0` (idempotent). Live proof:
`zramctl` → `/dev/zram0 zstd 8G [SWAP]`; `systemctl restart
zram-swap.service` re-ran ExecStart cleanly producing the zstd device.
`free -m` → Swap 8191 total. earlyoom unchanged and still armed.

Notable fix during review: the first converge produced lzo-rle because
writing `comp_algorithm` via sysfs after `zramctl --find --size` fails
with "Device or resource busy" — algorithm must go through
`zramctl --algorithm`. Caught by `zramctl` verification, playbook amended,
service restarted, re-verified zstd.

Also installed on idc02: `linux-modules-extra-6.8.0-151-generic` (113 MB —
zram.ko is NOT in linux-modules on Ubuntu generic kernels; verified via
`dpkg -c` of the .deb before installing).

## Audit-hosts compliance

`python3 scripts/audit-hosts.py --host idc02` → zram-swap.service observed
active, no missing-service delta. Remaining deltas are pre-existing and
unrelated: `jevos.service` undeclared running user service (sibling
OPS-1516 lane — worth declaring in expected_services), and
log-shipper/-severe failed oneshots (already tracked, OPS-1497).

## Caveats / follow-ups

- "earlyoom journal quiet over 7d" is a soak observation — mechanism is
  verified; watch the journal over the next week.
- Rollback: `swapoff /dev/zram0 && systemctl disable --now
  zram-swap.service` (or `-e zram_swap_enabled=false` to stop/disable via
  playbook); remove `zram_size` from hosts.yml to opt out.
- Fleet sweep idea (in job doc): any host with empty `swapon --show` has
  the same permanently-true earlyoom swap arm.

lessons:
- zram algorithm must be set via `zramctl --algorithm` (or sysfs
  comp_algorithm BEFORE disksize) — after --size initializes the device,
  comp_algorithm writes fail "Device or resource busy"; sysfs-write
  recipes under `|| true` fail silently.
- Ubuntu generic kernels ship zram.ko in linux-modules-extra-<kver>, not
  linux-modules — `modinfo zram` is the check; `dpkg -c` on the .deb
  proves contents before a 113 MB install.
- systemd oneshot services don't re-run ExecStart on converge when already
  active — after amending the setup script, `systemctl restart` is needed
  to exercise the new artifact; verify with zramctl, not unit state.
- ansible command/shell tasks skip in --check mode (registered vars
  empty) — probe-gated install logic can't be fully exercised in check.
