#!/bin/bash
# Installed into the container at /app/start-vms.sh (lives in vms-runtime/).
# No twm: the VMS desktop maps directly at 0,0 — a window manager forces
# interactive window placement (the "wireframe" outline) and eats the first click.
rm -f /tmp/.X11-unix/X99 /tmp/.X99-lock
Xvfb :99 -screen 0 1920x1080x24 &
sleep 3
x11vnc -display :99 -noxkb -forever -shared -rfbport 5900 -nopw -wait 50 -defer 30 -o /tmp/x11vnc.log &
cd /app
wine explorer /desktop=VMS,1920x1080 VMS.exe > /tmp/vms.log 2>&1 &
sleep 60
# Maximize the VMS window — it remembers its old ~1160x860 size, leaving the
# monitor panes at grid-res. Double-click the title bar to fill the desktop
# so hi-res snaps (vms-snap SINGLE_PANE_RECT) get real pixels.
DISPLAY=:99 xdotool mousemove 700 152 click --repeat 2 --delay 120 1 || true
tail -f /dev/null
