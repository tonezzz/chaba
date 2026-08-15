---
title: "tony-omen: 'Session Already Running' login blocker"
hostname: tony-omen
date: 2026-07-20
tags: [hardware, ubuntu, gdm, xrdp, chrome-remote-desktop]
status: active
---

# tony-omen — "Session Already Running" on local login

## Symptom

At the GDM login screen on `tony-omen`, after entering the password GNOME shows:

> Session Already Running  
> [Force Stop] [Cancel]

Clicking **Force Stop** does nothing and local login fails.

## Root cause

- Ubuntu 24.04+ / GNOME 46+ (here Ubuntu 26.04 / GDM 50) blocks a user from starting a second graphical session when logind already records an active session for that user.
- The **Force Stop** button in GDM is currently broken / non-functional for remote sessions.
- `xrdp` / `xrdp-sesman` registers an X11 session when a remote RDP connection is active.
- `chrome-remote-desktop@tony.service` used to register a `chrome-remote-desktop` X11 session even when no-one was connected; this package was removed on 2026-07-21.
- A leftover session (e.g., after closing an RDP client without logging out) therefore prevents local login.

## Quick fix (already applied 2026-07-20)

From another machine with SSH access:

```bash
ssh tony@tony-omen.local

# See active sessions
loginctl

# Stop the session-creating services and terminate the active remote session(s)
sudo loginctl terminate-session <SESSION_ID>
sudo systemctl stop xrdp xrdp-sesman chrome-remote-desktop@$USER.service

# Refresh the local login screen
sudo systemctl restart gdm
```

After the restart, local login works again.

## Permanent options

### Option A — Disable remote-desktop services if you do not need them

```bash
sudo systemctl disable --now xrdp xrdp-sesman chrome-remote-desktop@$USER.service
```

To remove them completely:

```bash
sudo apt remove --purge xrdp xorgxrdp chrome-remote-desktop
```

### Option B — Keep xrdp but stop it from blocking local logins (applied 2026-07-21)

`xrdp-sesman` registers its session as `Type=x11`, which GDM treats like a local GUI session. Make logind treat it as a text (`tty`) session by setting `XDG_SESSION_TYPE=tty` in the xrdp PAM stack.

1. Create an environment file:

   ```bash
   echo 'XDG_SESSION_TYPE=tty' | sudo tee /etc/security/pam_env_xrdp.conf
   ```

2. Edit `/etc/pam.d/xrdp-sesman` and add this line **before** `@include common-session`:

   ```
   session required pam_env.so envfile=/etc/security/pam_env_xrdp.conf
   ```

3. Restart xrdp:

   ```bash
   sudo systemctl restart xrdp xrdp-sesman
   ```

New xrdp sessions will then register as `Type=tty` in `loginctl` and no longer block GDM local login.

### Option C — Keep Chrome Remote Desktop

**Removed on 2026-07-21** because it always spawns an X11 session at boot and has no clean way to avoid blocking GDM local login. If it is reinstalled in the future, the workaround is to stop the service before local login:

```bash
sudo systemctl stop chrome-remote-desktop@$USER.service
```

### Option D — Use a separate user account for remote access

Create a dedicated account (e.g., `tony-remote`) for xrdp/CRD. Local `tony` logins are never blocked because the remote sessions belong to a different user.

## Final configuration (2026-07-21)

- `chrome-remote-desktop` package removed.
- `xrdp` kept with the PAM `XDG_SESSION_TYPE=tty` fix.
- `xrdp` and `xrdp-sesman` remain enabled for remote RDP access.

## How to check before a reboot

```bash
loginctl
# Look for any session for user tony with Type=x11, Remote=yes, or TTY=chrome-remote-desktop
# If present, terminate or stop the owning service before logging in locally.
```

## Related notes

- `hardware/tony-omen/2026-06-25-sensors.md` — hardware baseline for this machine.
