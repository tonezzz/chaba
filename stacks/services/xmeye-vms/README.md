# xmeye-vms — XMEye VMS DVR viewer (Podman, host-agnostic)

Windows XMEye VMS app under Wine in a Podman container: Xvfb :99 → x11vnc :5900 →
`wine explorer /desktop=VMS VMS.exe`. Console access via VNC or the noVNC web app.

## Layout

- `xmeye-vms.container` — Quadlet; `PublishPort` is the one per-host line (install.sh renders it)
- `start-vms.sh` — in-container startup; installed into `vms-runtime/` (no twm — see below)
- `install.sh` — run on the target host; renders bind IP, installs quadlet, enables service
- `verify.sh` — unit + listener + RFB handshake + container processes

## State (not in git)

- `~/.local/share/xmeye-vms/vms-runtime/` → `/app` — VMS.exe, config.ini (autologin), data/users/, qr/
- `~/.local/share/xmeye-vms/wineprefix/` → `/wine` — Wine prefix
- `~/.config/secrets/xmeye-dvr.env` — DVR credentials (copy out-of-band, never git)

## Moving the service to a new host

```bash
SRC=<source-host>  DST=<target-host>
# 1. image
ssh $SRC 'podman save localhost/xmeye-vms-x11vnc:latest' | ssh $DST 'podman load'
# 2. state
rsync -a $SRC:.local/share/xmeye-vms/vms-runtime $SRC:.local/share/xmeye-vms/wineprefix \
      $DST:.local/share/xmeye-vms/
# 3. secrets
scp $SRC:.config/secrets/xmeye-dvr.env $DST:.config/secrets/
# 4. install + verify on target
ssh $DST 'bash <repo>/stacks/services/xmeye-vms/install.sh'
ssh $DST 'bash <repo>/stacks/services/xmeye-vms/verify.sh'
# 5. only after the target verifies: stop (don't delete) the source instance
ssh $SRC 'systemctl --user disable --now xmeye-vms.service'
```

`install.sh [bind-ip]` — defaults to `tailscale ip -4`. The VNC listener has **no
password** (`-nopw`): always bind the host's tailscale IP, never LAN/0.0.0.0.

## Access

- Direct VNC: `vncviewer <host-tailscale-ip>:5900` (tailnet only)
- Browser: `https://tony-dell.taila0626a.ts.net/apps/vms/` — noVNC statics in
  `stacks/web/public/apps/vms/`, Caddy `/apps/vms/ws` → `websockify-vms-mn01.service`
  (127.0.0.1:6082) → `<bind-ip>:5900`. Route is gated to `Tailscale-User-Login`
  (funnel-safe). If the backend host changes, update the websockify target.

## Gotchas learned (2026-09-24, tony-dell → mn01)

- **No twm.** The original chain ran `twm` — it intercepts the first click as
  interactive window placement (the "wireframe" outline). Removed; the Wine
  desktop now maps at 0,0 and VMS renders without a click.
- **Stale X lock.** `podman restart` left `/tmp/.X99-lock` → Xvfb refused :99 and
  x11vnc/VMS died. start-vms.sh removes both socket and lock.
- **Cold prefix race.** First-ever `wine explorer` launch on a fresh prefix can
  silently fail to spawn VMS.exe; once the prefix is warm it works on every start.
  If VMS.exe is missing after start: `podman exec xmeye-vms-vnc wine VMS.exe`
  inside `/app` warms it, or just `systemctl --user restart xmeye-vms`.
- **Screenshot via raw RFB:** connect, send only `FramebufferUpdateRequest` —
  a `SetEncodings` message makes x11vnc drop the connection.
- DVRs (`noble-club`, `noble-a`) connect via XMEye cloud P2P, so any host works —
  only LAN-IP device entries would break off-network.
