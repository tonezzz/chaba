---
category: operations
---

# idc01 VPS Assessment

Recorded: 2026-09-26 (provider panel + live host probe; panel showed the VM
OFF at capture time — it booted ~19 min before the probe, so the panel is a
hard-reboot control, not a live view)

- **Machine:** idc01
- **Hostname:** idc01 (QEMU/KVM VM)
- **Provider hostname:** 157.85.110.99-995324364
- **User:** tony
- **Home:** /home/tony

## System

- **OS:** Ubuntu 24.04.5 LTS (kernel 6.8.0-142-generic)
- **Virtualization:** KVM
- **CPU:** 2 vCPU (QEMU Virtual CPU 2.5+)
- **RAM:** 12 GiB class (11Gi usable) — **upgraded from 8 GiB 2026-09-26**; the
  ~19:20 reboot was the resize power cycle (panel "OFF" = mid-transition)
- **Disk:** sda 100G (96G root fs, 34% used at probe)

## Network

| interface | address |
|---|---|
| public eth0 | 157.85.110.99/24 |
| tailscale | 100.74.146.0 |
| provider bandwidth (cumulative) | IN 17.88 GB / OUT 33.43 GB |

## Role

- Public VPS edge: Caddy listeners `0.0.0.0:80`/`443` (see
  `docs/ssot/infrastructure/ssot.security.idc01.yml`)
- Ada production host (`ada-pi-pwa`, `ada-ha-*` services)
- MDDB memory server (`127.0.0.1:11023`, tailnet-facing `100.74.146.0:11023`)
- Obsidian vault + open-notebook (migrated 2026-09-22/23)
- Legacy mn01 Caddy alias target

## Memory layout

- No disk swap (disk is a single 99G root); **zram swap added 2026-09-26**:
  `/dev/zram0` 6G, zstd, prio 100 via `systemd-zram-generator` +
  `/etc/systemd/zram-generator.conf`. Kernel module comes from
  `linux-modules-extra-<kver>` (installed — the `linux-image-virtual` flavor
  ships zram there, not in linux-modules).
- mddb.service cgroup drop-in (`mddb.service.d/mem.conf`): `MemoryHigh=8G`,
  `MemoryMax=10G`, `GOMEMLIMIT=3500MiB` — raised 2026-09-26 after corpus load
  (needs ~8.4G RSS) kept OOM-killing it under the old 5G/6.5G cap.

## Notes

- The provider panel "OFF" toggle is a power control — during the 2026-09-26
  check it showed OFF while the host was up 19 minutes post-reboot; treat the
  panel status as stale unless verified via `ssh idc01` / `tailscale status`.
- Bandwidth counters are cumulative from the provider; no per-host traffic
  baseline recorded yet.
