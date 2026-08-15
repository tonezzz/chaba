# Remmina RDP to tony-omen fails via hostname and IP

**Date:** 2026-07-21  
**Device:** tony-dell (client) → tony-omen (target, 192.168.1.48)  
**Protocol:** RDP over xrdp

## Symptoms

- Remmina could not connect to `tony-omen.local` or `192.168.1.48`.
- `ping tony-omen.local` failed (`Name or service not known`).
- `ping 192.168.1.48` succeeded.
- Ports 22 (SSH) and 3389 (RDP/xrdp) were open.
- `xrdp` on tony-omen was stopped; starting it allowed a terminal `xfreerdp3` test to authenticate, but the session immediately logged off.

## Root causes

1. **xrdp service was inactive** on tony-omen after a prior shutdown.
2. **Concurrent XFCE session conflict:** tony was already logged in locally on tony-omen (tty2), so a remote XFCE session collided with the existing D-Bus/session manager state.
3. **mDNS `.local` name** was unreliable for ICMP/ping from tony-dell.

## Resolution

### On tony-omen (target)

Start and enable xrdp:

```bash
sudo systemctl start xrdp
sudo systemctl enable xrdp
```

Isolate the remote XFCE session from the local one by editing `~/.xsession`:

```bash
cat > ~/.xsession <<'EOF'
#!/bin/sh
unset SESSION_MANAGER
unset DBUS_SESSION_BUS_ADDRESS
exec dbus-run-session -- xfce4-session
EOF
chmod +x ~/.xsession
```

### On tony-dell (client)

Add a static hosts entry for consistent `.local` resolution:

```bash
echo -e "192.168.1.48\ttony-omen tony-omen.local" | sudo tee -a /etc/hosts
```

### Remmina profile

- **Protocol:** RDP
- **Server:** `192.168.1.48` (or `tony-omen.local` after hosts entry)
- **Username:** `tony`
- Leave **Domain** empty for xrdp local logins.
- Accept the self-signed xrdp certificate on first connect.

## Verification

- `ssh tony@tony-omen.local 'systemctl is-active xrdp'` → `active`
- `xfreerdp3 /v:192.168.1.48 /u:tony` authenticated and kept the session open.
- Remmina connected successfully.

## Notes / next time

- If Remmina disconnects again immediately, check whether tony-omen already has a local XFCE session running (`ps aux | grep xfce4-session`). Logging out locally first is the simplest fallback.
- The `.local` hostname fix relies on the static `/etc/hosts` entry; if tony-omen gets a new DHCP lease, update the entry or configure reliable mDNS on the target.
