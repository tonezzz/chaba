# GUI freeze escalation — standard procedure

Symptom seen 2026-10-10: tony-dell GNOME — mouse moves, nothing responds.
ssh always survives a GUI freeze; work the ladder from least to most
invasive and **stop at the first rung that recovers control**.

## Ladder

1. **Diagnose over ssh** — `ssh tony-dell`; check `uptime` (load),
   `free -h` (OOM pressure), `journalctl -b -p err | tail`. High load /
   OOM → the freeze is resource starvation, not the compositor — kill
   the hog instead.
2. **Restart the shell only** — `sudo killall -3 gnome-shell`
   (SIGQUIT → systemd/gdm respawns it). Apps survive. Mouse-moving-but-
   no-control freezes are usually shell-level and end here.
3. **Greeter fallback** — if the shell won't respawn, the session
   collapses to the gdm login screen. Log in fresh; apps are lost but
   services (containers, timers, HA) never stopped.
4. **Restart the display manager** — `sudo systemctl restart gdm`.
   Closes *everything* GUI — all apps die, back to login. Still zero
   service impact.
5. **Full reboot** — last resort, only if the greeter itself is
   unresponsive or the GPU/driver is wedged. On tony-dell this takes
   down HA + apps for ~3 min — say so before running it.

## Notes

- `killall -3` needs root even for your own session's shell.
- A frozen greeter at rung 4/5 usually means a hung GPU/mutter — the
  journal will show it (`journalctl -b -g "gnome-shell|mutter|gpu"`).
- The vcast/kiosk displays (vcast-screens-card, `/apps/vcast`) are
  **separate** from the physical GNOME session — a "screen" that won't
  respond in the admin dashboard is a websocket/display problem, not
  this ladder. Check `/api/input-bridge/displays` instead.
