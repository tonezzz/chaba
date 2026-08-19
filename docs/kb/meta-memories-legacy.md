---
title: "Persistent memory index — recurring issues and known fixes"
category: operations
date: 2026-07-21
tags: [meta, memory]
status: active
---

# Memories — recurring issues and known fixes

Use this file as the first place to check when a known symptom reappears. Each entry links to the detailed note.

## How to add a memory

1. Note the trigger/symptom, root cause, fix, and the file where details live.
2. Keep it short enough to scan quickly.
3. Update this file whenever a known issue is fixed or changes.

---

## tony-omen (HP Omen 15-BC)

### GDM "Session Already Running" at local login

- **Trigger / symptom:** After entering the password at the GDM login screen, a dialog says **Session Already Running** with a non-working **Force Stop** button.
- **Root cause:** Ubuntu 24.04+ / GNOME 46+ (here Ubuntu 26.04 / GDM 50) blocks a user from opening a second graphical session. `xrdp` and Chrome Remote Desktop register `Type=x11` logind sessions for the same user, so local login is refused. The Force Stop button is broken for remote sessions.
- **Fix:**
  1. From another machine, SSH in: `ssh tony@tony-omen.local`
  2. Kill stale remote sessions:
     ```bash
     loginctl
     sudo loginctl terminate-session <SESSION_ID>
     sudo systemctl stop xrdp xrdp-sesman chrome-remote-desktop@$USER.service
     sudo systemctl restart gdm
     ```
  3. Permanent prevention:
     - Apply the xrdp PAM `XDG_SESSION_TYPE=tty` fix (`hardware/tony-omen/2026-07-20-session-already-running.md`).
     - Remove `chrome-remote-desktop` (done 2026-07-21).
- **Reference:** `hardware/tony-omen/2026-07-20-session-already-running.md`

---

## Android TV box (`sailfish` / `rk3328_box`)

### WiFi disconnects immediately after `COMPLETED` (`networkId=-1`)

- **Trigger / symptom:** `wpa_supplicant` authenticates to `TONY-WIFI_2.4G` but the Android WiFi service tears the connection down with `reason=3` and `networkId=-1`.
- **Root cause:** The Android WiFi HAL expects an internal `WifiConfigStore` network ID for every connection. Manually injecting the network into `wpa_supplicant` bypasses that mapping, so the HAL cannot reconcile the completed WPA association and calls `disconnect()`.
- **Fix:**
  1. Disable the Android WiFi service: `svc wifi disable`
  2. Run `wpa_supplicant` directly with a manual config (`/data/vendor/wifi/wpa/wpa_supplicant_manual.conf`).
  3. Assign a static IP because no DHCP client runs when the WiFi service is off.
  4. Use Termux:Widget shortcuts for one-tap reconnect/MCP restart.
- **Reference:** `projects/android-box/README.md`

### MCP `run_shell` needs root access

- **Trigger / symptom:** Commands that need root (e.g., `wpa_cli`, `ifconfig`) fail when called through MCP.
- **Root cause:** The MCP server ran as the Termux user; Android privileged binaries require `su 0 -c '...'`.
- **Fix:** Added a `root` boolean parameter to `run_shell`; when true, the command is wrapped with `su 0 -c` and the correct `PATH`.
- **Reference:** `projects/android-box/README.md`

---

## tony-dell (Dell OptiPlex 7040)

### Internal HDD pending / offline uncorrectable sectors

- **Trigger / symptom:** SMART check shows pending or offline uncorrectable sectors on the Seagate HDD.
- **Root cause:** Physical drive wear; not immediately fatal, but a warning sign.
- **Fix:** Monitor; no hardware change applied yet. Re-run SMART periodically.
- **Reference:** `hardware/tony-dell/2026-06-25-sensors.md`
