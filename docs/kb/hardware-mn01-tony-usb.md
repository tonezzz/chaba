# mn01 — Fujitsu ESPRIMO Q556/2 (real hardware)

mn01 is a real box, not just a tailnet identity. Verified 2026-10-10 after
power-cycle (LAN `192.168.2.81`, tailnet `100.106.196.22` reclaimed).

## Hardware

- Fujitsu **ESPRIMO Q556/2** mini PC — Intel **i5-7400T** (4c Kaby Lake),
  7G RAM, Micron 1100 **238G SATA SSD** (26% used), DVDRAM drive
- NICs: `enp1s0` gigabit ethernet (UP) + `wlx881100c50a2c` **USB wifi
  dongle — down/no carrier** (its saved creds likely point at the old
  mn-home SSID; ethernet is the reliable path)
- Hosts VMs (`vms-snap.service`, `virbr` 192.168.123.x, dnsmasq :53)

## What runs (verified alive)

- `runner-agent` — kanban claim+execute lane (devin-dispatch, cap ~2)
- `devin-dispatch-watch.timer`, `chaba-repo-sync.timer`
- `log-shipper.timer` + `log-shipper-severe.timer` (→ MDDB host-logs)
- `ada-standby-sync.timer` (03:15) + `mn01-canary.timer` (03:30)
- Tailnet listeners: :8004 (Ada standby), :3939, :5900, :8780–8782
- Ada-ha standby units stopped/disabled since 2026-09-24 (by design)

## Outage record

Dark ~Oct 5 → Oct 10 (~5 days): box powered off / NIC down silently —
nobody noticed because all its live services are standby/dormant.
Lesson: it needs a staleness canary on tony-dell (mn01-canary exists
but is local — useless when the host is down; carded idea: external
pinger for host-down detection).

## tony-usb stick

Portable Ubuntu stick (117G, `ubuntu-usb` ext4 + EFI). Boots any host
fleet-ready: sshd + fleet authorized_keys baked, tailscale present.

**Caveat (verified 2026-10-10):** the stick carries a *clone of mn01's
node key* — booting it anywhere steals the `mn01` tailnet session from
the real box. When both are up they fight for 100.106.196.22. Policy:
`mn01-stick-standard.md` — fix pending: stick should get its own node
key (e.g. `tony-usb`), not mn01's.

First-boot fix on stick image (no curl, sshd not enabled):
`sudo apt install -y curl && sudo systemctl enable ssh`
