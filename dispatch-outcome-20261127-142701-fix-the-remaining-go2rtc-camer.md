# Dispatch outcome — go2rtc-7-camera-producers-return-empty-f-cc9176 (attempt 2)

Card: `go2rtc-7-camera-producers-return-empty-f-cc9176`
Date: 2026-11-27 (~14:27–15:10 +07), host tony-dell → target tony-omen

## Result

**Software side is now fully self-healing; done-condition remains blocked by
hardware — all 3 cameras are still off the network (L2).**

Re-verified on omen: fresh ping-sweep of both LAN /24s finds none of the
camera MACs (xiaomi_c100 `b8:88:80:cb:7d:2c`, xiaomi_c201
`d8:3a:36:7d:10:0d`, ip_cam_65 `d4:9e:3b:6a:94:90`). All 7 target
producers still return `200/0B`; `omen_cam` healthy (~30KB). DHCP churn is
live: cloud device_list reports c100 at `192.168.2.92`, but that IP's ARP
MAC is the HP DeskJet printer — cloud `localip` is stale, only MAC-verified
resolution is trustworthy.

## What changed (tony-omen, ~/.config/go2rtc/)

- `xiaomi-cam-resolve.py` rewritten (backup `.bak-20261127`): two-pass —
  ARP-MAC-check each cloud IP, then ONE throttled sweep of **all local
  /24s on physical interfaces** matching all pending cams. Physical-iface
  filter (eno*/wlo*/wlan*/eth*) is essential — unfiltered `scope global`
  sweep hit 8 prefixes (~2000 pings) incl. docker/libvirt/tailnet and
  would blow the job's 2m timeout. Verified: prefixes `[192.168.0,
  192.168.2]`, dry-run exit 0.
- NEW `ipcam65-ip.sh`: runtime IP resolver for ip_cam_65 (VStarcam has no
  cloud API). MAC `d4:9e:3b:6a:94:90` → IP via `ip neigh` + TCP/10554
  verify; 300s pos/neg caches; falls back to `.71`. Cold ~8s, warm ~25ms.
  Deliberately does NOT match "legacy" MAC `cc:50:e3:19:a0:2f` — that is a
  different live device at .70 (port closed).
- `ip_cam_65_{auto,hd,low}.sh` rewritten to use the helper; `CAM=` line in
  `rotate-ipcam65.sh` + `ipcam65-rotate-finisher.sh` patched — the armed
  credential rotation now fires on camera return at ANY IP.

## What changed (repo, this branch)

- Cherry-picked attempt-1 commit `5272be200ac` (its auto-merge had failed
  on conflict resolution; skipped its unrelated assessment-stats churn).
- `ssot.jobs.yml` note updated; `ssot.ip-camera.yml` documents the resolver.
- `ssot.services.yml` go2rtc entry corrected: real server is system
  `go2rtc-omen.service` (:1984 owner); the enabled user `go2rtc.service`
  is a degraded duplicate — this stale entry caused the token-refresh
  wrong-unit bug. Left enabled on-host (possible accidental failover —
  flagged for Tony).
- MAC registry corrected: `bedroom-remote` → `xiaomi-c201` (MAC
  `d8:3a:36:7d:10:0d` is the C201 camera per go2rtc cloud device_list —
  a MAC can't be two devices). Fixed in both mac registries,
  ip-address-registry, and the generated ui file.
- Job doc: `docs/ssot/jobs/infrastructure/2026-11-27-go2rtc-cam-ip-resolver-hardening.yml`

## How to verify

- `ssh tony-omen 'journalctl --user -u xiaomi-cam-resolve.service -n 20'`
- `ssh tony-omen '~/.config/go2rtc/ipcam65-ip.sh'` → prints `192.168.2.71` (offline fallback)
- Once cameras rejoin: xiaomi IPs self-rewrite ≤5min; ip_cam_65 resolves at
  exec time; then all `frame.jpeg?src=` return non-zero bytes.

## Blockers / follow-ups

- Physical: power/WiFi at the camera location — needs hands (all 3 down
  simultaneously suggests shared power/AP). Tony answered "proceed" but
  cameras have not rejoined as of ~15:05.
- Optional: DHCP reservations on the ZTE for the 3 camera MACs.
- Decide fate of zombie user `go2rtc.service` on omen (disable vs keep as
  failover) — flagged on card.

lessons:
- "scope global" ip-addr sweeps must be filtered to physical interfaces — docker/libvirt/tailnet prefixes turn a /24 sweep into ~2000 pings and blow job timeouts.
- go2rtc cloud device_list `localip` is stale/unreliable — always ARP-MAC-verify before rewriting camera IPs; a "pingable" IP can be a different device entirely (HP printer impersonated c100's cloud IP).
- Registry MAC "conflicts" can be real different devices — cc:50:e3:19:a0:2f looked like ip_cam_65's legacy MAC but is a live non-camera; port-probe before trusting a MAC→device mapping.
- A registry label ("Bedroom IR remote") can be a months-old misidentification — the Xiaomi cloud device_list is authoritative for its own devices' MACs.
- Dispatch attempt branches can fail auto-merge on unrelated generated-file churn; cherry-picking just the fix commit into the next attempt's branch keeps the work landable.
