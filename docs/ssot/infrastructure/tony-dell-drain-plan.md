# tony-dell Drain Plan — workload off dell to idc03/omen/mn01

> **Status:** Phase 1 — inventory + decision table. Approved end-state (Tony,
> 2026-10-21): dell = **minimal base** (ssh + tailscale + chrome-remote-desktop
> + heartbeat cron) — a remotely reachable spare box. Everything else moves out.
> **Date:** 2026-10-21 · **Precedent:** `idc01-to-idc03-migration-plan.md`
> (same playbook: inventory → waves → soak → decommission).
> **Context:** root was migrated HDD→NVMe 2026-10-20; free user data already
> moved to `idc02:~/dell-moved-20261020/`.

## Destination capacity (verified 2026-10-21)

| Host | RAM free | Disk free | Verdict |
|---|---|---|---|
| idc03 | ~7.7 G avail / 16 G | 115 G / 290 G | **primary target** — Ada+mddb-primary already lives here |
| idc02 | ~3.9 G avail / 15 G | **31 G / 290 G (90%)** | NOT a services target; cold-data/edge only. ⚠ grew +145 G in 24h — investigate |
| omen | laptop | — | home-LAN items only (may sleep) |
| mn01 | small | — | always-on home-LAN box — best host for home-net watchdogs |

## (a) Live inventory on tony-dell

### Docker containers (5 + 1 ephemeral)
| Container | Role | Decision |
|---|---|---|
| chaba-postgres-16 | pgvector postgres — board/CMS DB | **M → idc03** (containerize as quadlet or keep docker) |
| redis | cache | **M → idc03** with postgres |
| trade-api | trade service (:9000) | **M → idc03** |
| trade-automation | trade scripts | **M → idc03** |
| web (caddy) | serves kanban `stacks/web/public`, `docs`, h3 public, **and yt-live-media corpus** | **M → idc03** for board; media route → idc02 edge (re-mount gdrive there) |
| clever_booth | ephemeral test | **R** drop |

### Timers (32 active)
| Group | Units | Decision |
|---|---|---|
| Board/CMS ops | board-statics-sync, chaba-cms-reflect, chaba-jobs, chaba-repo-sync*, chaba-served-mirror-sync, chaba-services-regen, chaba-system-report, check-serve-config, cms-h3-publish, devin-dispatch-prune, mcp-debug-h3-sync, ssot-optimization-snapshot, staleness-sentinel, timer-sentinel, ops-percussion, chaba-route-health | **M → idc03** (*repo-sync: retire — it exists to sync dell's exec checkout) |
| HA-adjacent | ha-auth-watch, network-scan-tony | **M** — ha-auth-watch → idc03; network-scan-tony (home-LAN scan) → **mn01** |
| Dell-health | chaba-dell-health-agent, tony-dell-health-snapshot, tony-dell-mcp-health, tony-dell-monitor | **R** — retire (spare box doesn't need the agent fleet) or collapse to one lightweight check |
| KVM/display | barrier-client-watchdog, barrier-enforce-lan, barrier-pin-vt | **R** — drops with KVM stack |
| Log shipping | log-shipper, log-shipper-mha, log-shipper-severe, log-shipper-severe-mha | **M → destination of log pipeline** (likely idc03) — verify targets first |
| Stock | ubuntu-insights-*, launchpadlib-cache-clean, snap.firmware-notifier | **R** — stock, drop from tracking |

### User/system services
| Unit | Role | Decision |
|---|---|---|
| kanban single-writer (`chaba-tony-dell` checkout + kanban-commit lane) | THE board writer | **M → idc03** — critical cutover; idc03 has checkout already (chaba-kanban-sync exists) |
| web.service (caddy quadlet) | see containers | M |
| chaba-tunnel | reverse ssh → omen :7022 | **K** — keep (cheap spare-box reachability alongside tailscale) |
| dnsmasq-postgre | DNS alias for postgres | **R** — follows postgres off |
| rclone-gdrive | gdrive FUSE mount serving media corpus | **M → idc02** (with media caddy) — no disk cost (remote mount) |
| tailscale-serve-8080 | tailnet serve for board | **M → idc03** with web |
| xfce-seat, xvfb-99, barrier-client | physical/headless display + KVM | **R** — CRD covers remote display |
| xrdp, xrdp-sesman, xorg-seat | RDP stack | **R** — CRD suffices |
| chrome-remote-desktop-env | remote desktop | **K** — minimal base |
| sync-to-hdd (system) | old HDD-backup sync | **R** — obsolete post-NVMe (or repurpose NVMe→HDD backup — Tony call) |
| tony-dell-wan-failover (system timer) | home multi-WAN failover check | **M → mn01** (always-on home box) |
| cups, cups-browsed | printing | **R** — spare box doesn't print (Tony veto ok) |
| tailscaled, sshd, ufw, chrony, NM, smartmontools, unattended-upgrades, gdm | base OS | **K** |

### Cron
| Entry | Decision |
|---|---|
| `* * * * * ~/chaba/tony-dell.sh` (h3 "Tony Dell online" heartbeat) | **K** — reports the spare box alive; update target if h3 endpoint moves |
| `*/10 * * * * devin-desktop-watchdog.sh` | **R** — devin-desktop leaves with workload |

### Data / state
| Path | Decision |
|---|---|
| `~/.config/secrets/` (~20 envs + archives) | **M → idc03** (merge carefully — it has its own) + keep copy on dell for spare-box use |
| `~/.config/home-assistant` (3.9G old tony-ha config) | **A** — archive to idc02 or drop (tony-ha lives on omen since ph5) |
| `~/.config/ada-ha`, `~/.config/michael-dev` | **M → idc03** |
| `~/.config/containers` (8.3G podman) | moves with quadlets; **`.parked` + `migrated-off/` already on idc03 → verify then drop** |
| `~/CascadeProjects` (15G) | `chaba-tony-dell` → idc03 writer checkout; **rest → verify no uncommitted work, then drop** (github has history) |
| `~/.local` (11G), `~/go`, venvs, npm caches | **R** — drop with services |

## (b) Cutover waves

```
0. Approve this table + fix open questions
1. rsync secrets/configs → idc03/idc02 (non-destructive)
2. postgres+redis+trade+web → idc03 (docker or quadlets), verify parity
3. SINGLE-WRITER handoff dell→idc03 (gate: kanban-commit off dell first,
   idc03 writer armed via install-hooks + check-single-writer)
4. Timers → idc03 in batches (verify first runs green)
5. Home-anchored: wan-failover + network-scan → mn01; media-caddy+gdrive → idc02
6. Consumer repoint: grep fleet for 100.68.142.13/tony-dell service refs
   (board-api URL!, tailscale-serve, dnsmasq-postgre consumers)
7. Soak 24–48 h → THEN strip dell to minimal base
```

## Decisions (Tony, 2026-10-21)

1. `~/.config/home-assistant` 3.9G — **DROPPED** (verified tony-ha runs on omen container; dell copy was the stale pre-ph5 config).
2. Media corpus → **relocate** — caddy media route + rclone gdrive mount → idc02 edge (rclone.conf already staged on idc02, wave 1).
3. sync-to-hdd → **REPURPOSED** as NVMe→HDD bootable clone (`/usr/local/bin/nvme-hdd-clone.sh`, weekly `sync-to-hdd.timer`, `--exclude=/etc/fstab` keeps sda5 self-consistent; first seed running 2026-10-21). This replaces the frozen Oct-20 rollback with a refreshed clone — intended.
4. cups → **KEEP** (dell returns to service — printing retained).
5. idc02 90% explained: `hf-cache-archive-202610` 68G + `mddb-backups-idc01-retired` 64G — archive payload, not a leak. Open: is the retired-idc01 pile redundant with idc03's own 56G mddb-backups?

## Wave status

- **Wave 1 done (2026-10-21):** `~/.config/secrets/` → `idc03:~/.config/secrets/from-dell-20261021/` (staged, no clobber — merge when units install); `ada-ha`/`michael-dev`/`caddy` configs → `idc03:~/.config/dell-lane-configs/`; `rclone.conf` → idc02.
- Waves 2–7 pending.
