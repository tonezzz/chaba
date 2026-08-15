---
hostname: tony-omen
date: 2026-07-21
tags: [hardware, changelog]
status: active
---

# tony-omen — Change log

| Date | Change | Reason | Result | Reference |
|------|--------|--------|--------|-----------|
| 2026-06-25 | Sensor & disk health check | Establish hardware baseline | All temperatures normal, NVMe SSD healthy (5% wear), battery 100% / 0 cycles | `hardware/tony-omen/2026-06-25-sensors.md` |
| 2026-07-20 | Cleared stale xrdp/Chrome Remote Desktop sessions and restarted GDM | GDM showed "Session Already Running" and local login failed | Local login restored | `hardware/tony-omen/2026-07-20-session-already-running.md` |
| 2026-07-21 | Applied xrdp PAM `XDG_SESSION_TYPE=tty` fix | Prevent xrdp sessions from being treated as graphical sessions that block GDM | New xrdp sessions register as `Type=tty`; local login no longer blocked by xrdp | `hardware/tony-omen/2026-07-20-session-already-running.md` |
| 2026-07-21 | Removed `chrome-remote-desktop` package and unused deps (`xbase-clients`, `xserver-xorg-video-dummy`) | CRD always spawns an X11 session at boot and has no clean way to avoid blocking GDM local login | CRD no longer creates a conflicting X11 session; `xrdp` remains the remote access method | `hardware/tony-omen/2026-07-20-session-already-running.md` |
| 2026-07-21 | Updated IP in KB dashboard/context to `192.168.1.48` via `tony-omen.local` | Current-context refresh | Dashboard now uses the current lease / mDNS name | `current-context.md`, `hardware/README.md` |
| 2026-07-23 | Added Caddy route `/tony-omen/apps/imagen` with Docker inference proxy | Host the Imagen UI and API on the local web server | UI live at `http://192.168.1.48:8080/tony-omen/apps/imagen/`; API health 200; 512x512 generation tested in ~62s | `tasks/2026-07-23-tony-omen-imagen-website.md` |
