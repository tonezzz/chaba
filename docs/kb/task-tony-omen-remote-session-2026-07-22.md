# tony-omen Remote Session Setup

**Date:** 2026-07-22  
**Device:** tony-omen (192.168.1.48)  
**Client:** tony-dell (192.168.1.42)  
**Status:** Completed

## Problem
- RDP/xrdp connection from `tony-dell` to `tony-omen` created a new session on every reconnect instead of reusing the previous RDP session.
- RDP session was separate from the physical console session on display `:0`.

## Root Causes
1. **xrdp session persistence disabled:** `/etc/xrdp/sesman.ini` had `KillDisconnected=true` and `DisconnectedTimeLimit=60`, killing disconnected sessions after 60 seconds.
2. **Console sharing not supported by xrdp:** xrdp starts a new Xorg session (`:10`) and cannot attach to the existing physical session (`:0`).
3. **x11vnc already present but localhost-only:** An `x11vnc-gdm.service` existed for display `:0`, but listened only on `127.0.0.1:5900`.

## Fixes Applied

### On `tony-omen` (192.168.1.48)
- Edited `/etc/xrdp/sesman.ini`:
  ```ini
  KillDisconnected=false
  DisconnectedTimeLimit=0
  ```
- Restarted `xrdp-sesman`.
- Modified `/etc/systemd/system/x11vnc-gdm.service`:
  - Replaced `-localhost` with `-allow 192.168.1.42`
  - Now listens on `0.0.0.0:5900` and accepts connections only from `tony-dell`
- Reloaded systemd and restarted `x11vnc-gdm.service`.
- Backed up original service file to `/etc/systemd/system/x11vnc-gdm.service.bak`.

### On `tony-dell` (192.168.1.42)
- Synced both Remmina RDP profiles to use `network=autodetect` so xrdp sees identical connection params.
- Set `clientname=tony-dell` in both profiles (mainly relevant for Windows; harmless for xrdp).
- Created Remmina VNC profile:
  - `~/.local/share/remmina/pc_vnc_tony-omen-console_192-168-1-48.remmina`
  - Protocol: VNC
  - Server: `192.168.1.48:5900`
  - Name: `tony-omen console (VNC)`

## Result
- RDP reconnect now reuses the same xrdp session.
- VNC profile connects to the physical console session (`:0`) on `tony-omen`.
- Access is restricted to `192.168.1.42`; no VNC password is currently set.

## Files Changed
- `/etc/xrdp/sesman.ini`
- `/etc/systemd/system/x11vnc-gdm.service`
- `/etc/systemd/system/x11vnc-gdm.service.bak`
- `~/.local/share/remmina/pc_rdp_tony-omen-(192-168-1-48)_192-168-1-48.remmina`
- `~/.local/share/remmina/pc_rdp_tony-omen-local_tony-omen-local.remmina`
- `~/.local/share/remmina/pc_vnc_tony-omen-console_192-168-1-48.remmina`

## Next Steps
- Continue configuration work on `tony-omen` remote session.
- If a VNC password is preferred over IP-based restriction, generate one with `x11vnc -storepasswd` and update the service.
