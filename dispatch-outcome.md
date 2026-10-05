# Dispatch outcome — vcast-cast-lane audit

**Result: lane healthy after two fixes; both verify scenarios PASS; metric met (0.6s < 5s).**

## Service health (verified 2026-10-05 ~15:10–15:50 +07)

| Service | Host | State | Notes |
|---|---|---|---|
| cast-browser.service | tony-omen :8799 (LAN) | active, 3d | headless Chrome+Playwright; 175MB, 153 tasks |
| cast-shots-http.service | tony-omen :8090 | active | binds LAN IP by design (Chromecast fetches) |
| cast-desktop@0 | tony-omen | failed/disabled | exits when :0 idle-asleep — retirement decision open |
| cast-desktop@1 | tony-omen | **was flap-looping, now stopped** | 17,368 restarts on nonexistent display :1; unit already disabled → `systemctl --user stop` applied |
| cast-browser-proxy.service | tony-dell :8799 | active | socat 127.0.0.1:8799 → omen 192.168.2.86:8799; verified end-to-end |
| cast-ha-panel.timer | tony-dell | **was dead, fixed** | see below |
| yt-live-api.service | tony-dell :8791 | active | `{"ok":true}`; last job complete (49 segs) |
| audit-cast.timer | tony-dell | active | 5-min host audit healthy; WARNs real (c201 consumer flaps) |
| input-bridge relay | idc01 :3010 | healthy | 7 screens registered, `{"captures":{}}` — no stale leases |

## Fixes applied

1. **cast-ha-panel.timer dead since boot (14d).** `OnUnitActiveSec=60s` is self-rearming relative to the service's last activation; after reboot it never runs so the timer never fires — `tv_display=camera` was silently not casting. Added `OnActiveSec=2min` to `~/.config/systemd/user/cast-ha-panel.timer` (host-local, `.bak-20261005` kept), daemon-reload, timer restarted → now ticking every 60s and re-casting `xiaomi_c201` → TONY-TV (play_stream 200, mediashell live, go2rtc consumers=1). Rollback: restore `.bak` + daemon-reload.
2. **cast-desktop@1 flap loop on omen stopped** (`systemctl --user stop`). Unit was already `disabled`, so no persistence lost; `systemctl --user start cast-desktop@1` revives if ever needed.

## Lease wiring

Ada → `VCAST_API` (`https://tony-dell.taila0626a.ts.net/api/input-bridge` → Caddy → idc01:3010) → `GET/POST /capture` screen leases + `/camwall` zones + `/pub`. Verified live; post-run lease table clean (`{}`). Note: Ada's `tv_action` calls cast-browser **directly** at `http://100.75.102.88:8799` (tailnet) — the dell :8799 socat proxy is loopback-only for dell-local callers (cast-ha-selected.sh `/tick`).

## Scenario verification (ran on idc01, ada-ha-tony ws://127.0.0.1:8002/ws)

- `cam_to_screen` — **PASS** 4/4 turns (VMS snap ~28s → cast delivered → teardown)
- `cctv_snapshot_to_screen` — **PASS** 1/1 (note: Ada substituted pool camera because xiaomi_c201 was flapping `unavailable` at run time — reasonable, but watch that camera)

## Metric

- **Cam cast to first frame on vcast screen: 0.6s** (go2rtc frame → POST /frame → /pub image → screen state=image, screen 7). PASS vs <5s.
- TV path (Chromecast): warm re-cast <1s dispatch; cold receiver wake ~15–20s (app launch + HLS buffer).

## SSOT changes (committed on dispatch branch `dispatch/20261005-145917-audit-the-cast-lane-services-c`, commit e7b32084)

- `docs/ssot/apps/ssot.apps.vcast.yml` — new section **"Cast lane — host topology & single points"**: documents the tony-omen SPOF (what dies: tv_action/assist sentences/desktop casts/cast-shots; what survives: all of vcast, cast-cam, yt-live, cast-ha-panel fallback via cast-ha-page.sh), proxy topology, lease wiring, measured metrics.
- `docs/ssot/jobs/infrastructure/2026-10-05-vcast-cast-lane-audit.yml` — full job lifecycle artifact.

## Watch items / follow-ups

- `xiaomi_c201` flaps idle↔unavailable — audit-cast WARNs are a real go2rtc producer issue (known, still open).
- Weekly `ada-scenario-casting.service` timed out at its 2h cap on 2026-10-03 (`Result=timeout`, ExecMainStatus=15) — suite duration vs budget worth a look; `cctv_snapshot_to_screen` has zero historical reports.
- `vcast_snapshot` self-snap timed out once on screen 6 (cam_to_screen T3) — screen was showing the image; snap-request round-trip lapsed.
- Repo-track `cast-ha-panel.{service,timer}` + `cast-ha-selected.sh` + `audit-cast.sh` (host-local only today — same gap flagged by the audit-cast card).
- `cast-desktop@0` on omen: retire or keep? (`verify-cast-instance-needed` already flagged in ssot.audit.hosts.yml)

## Verify

```
systemctl --user list-timers cast-ha-panel.timer   # NEXT populated, 60s cadence
curl http://127.0.0.1:8799/                        # {"err":"unknown path"} = proxy→omen alive
curl http://127.0.0.1:8791/health                  # {"ok":true}
curl http://100.74.146.0:3010/capture              # {"captures":{}}
ssh tony-omen 'systemctl --user is-active cast-desktop@1'   # inactive
```
