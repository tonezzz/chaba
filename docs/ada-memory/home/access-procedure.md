---
key: access-procedure
kind: procedure
status: active
subject: remote-access
scope: shared
source: vault
written_by: tony
last_verified: 2026-09-23
---

How to reach things. Everything admin-facing is tailnet-only: ssh <host> works by tailnet name (tony-dell, mn01, idc01, michael-ha). HA web UIs are Tailscale HTTPS — tony-ha at https://tony-dell.taila0626a.ts.net:8123. MDDB health: curl http://100.74.146.0:11023/health; its systemd unit on idc01 is mddb.service (systemctl --user restart mddb.service). If idc01 freezes (tailscale pings but SSH hangs), use the Siamdata VPS panel console to reboot. Dashboard changes on tony-ha go through the lovelace websocket — no restart needed.
