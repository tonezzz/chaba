# Dispatch outcome — kk-macbook-ubuntu (T2 fork spec)

## What was found

The dispatch spec assumed a T2 Mac and a full install task. Reality: the card was
already executed by a session on 2026-10-10 — and the machine turned out to be
**MacBookPro13,3 (2016 15" Touch Bar, PRE-T2)**, not the suspected 2018 T2 model.
Serial-prefix inference had misled the spec; DMI is authoritative.

Verified live state (ssh tony@100.77.76.112):
- Ubuntu 26.04.1 LTS, kernel 7.0.0-38-generic, whole-disk ext4+EFI on nvme0n1 — macOS wiped
- tailnet `tony-macbook` 100.77.76.112 (own node, NOT the mn01 stick identity); LAN 192.168.2.88 via USB-C ethernet dongle
- WiFi wlp3s0 up via brcmfmac (BCM43602) — works but no AP associated (backup has SSIDs only, no PSKs); Bluetooth ok
- Backup on the ubuntu-usb stick (still mounted `/run/media/tony/ubuntu-usb`):
  `home/tony/macbook-backup-2026-10-10` — 23G kkkakk home + 211M Shared, incl.
  `.ssh/authorized_keys`, chaba-health, Library/CRD config, .anydesk
- NOT backed up: podman redis-data volume (no .rdb/.aof exists — treated disposable)
- Gaps: no runner-agent, no podman/redis, no PlayLive/CDP, no mcp-debug, no WiFi profile

## What this session did

- **SSH rejoin**: seeded authorized_keys on the laptop with the 3 fleet keys from the
  macOS backup; repointed `Host macbook` in ssh-config on tony-omen AND tony-dell
  (100.124.59.112 → 100.77.76.112, user kkkakk → tony; removed stale `Host 100.124.59.112`
  block on dell). Verified `ssh macbook` end-to-end from both hosts.
- **audit-hosts.py**: HOSTS macbook → `{tailnet: tony-macbook, os: linux, user: tony}`;
  live run passes with zero deltas.
- **SSOT sweep** (31 files): mysystem.macbook.yml rewritten to Linux (v6);
  macbook-appdev.yml dropped; host-roles, mcp-debug(+files+capture), audit.hosts,
  security.tony-macbook+index, ip+mac registries, multi-wan, host-tools, services,
  playlive-hosts, mcp-tools, night-jobs(+macbook), automation.macbook, cleanup,
  focus.triage, reports, mysystem.home, index, registry.ssot-extra, follow-up,
  registry.script-core.
- **Card**: moved to `review` (autonomy t3 — human closes), note/brief updated to
  truth, 3 `requests:` recorded + board-api request posted, full comms.
- **Trail**: docs/ssot/jobs/infrastructure/2026-10-11-tony-macbook-ubuntu-rejoin.yml

## Result

Card effectively complete; in `review` awaiting Tony on:
1. Revoke dead tailnet node `kk-macbook` (100.124.59.112) — admin console, can't be done from a node.
2. One manual Wi-Fi join on the laptop (no PSK recoverable).
3. Optional restores: KK files into ~/, redis (no backup), runner-agent lane — defaults documented.

Also noted: `playlive-macbook-tunnel.service` on tony-dell now connects but forwards
to a dead endpoint — safe to disable; `ssh-mesh-sync` macbook exclusion is now stale.

## Verify

- `ssh macbook 'hostname; uname -a'` from tony-omen or tony-dell → tony@tony-macbook, Linux
- `python3 scripts/audit-hosts.py --host macbook` → no deltas
- `node scripts/ssot-validate-all.mjs` → 0 errors (ran full sweep; fixed one self-inflicted YAML break)
- Commit `ffed2889f` on branch `dispatch/20261011-065857-t2-fork-likely-if-hw-model-mac` (not pushed)
