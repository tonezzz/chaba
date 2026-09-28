#!/bin/bash
# Installed into the container at /app/start-vms.sh (lives in vms-runtime/).
# No twm: the VMS desktop maps directly at 0,0 — a window manager forces
# interactive window placement (the "wireframe" outline) and eats the first click.
rm -f /tmp/.X11-unix/X99 /tmp/.X99-lock
Xvfb :99 -screen 0 1280x720x16 &
sleep 3
x11vnc -display :99 -noxkb -forever -shared -rfbport 5900 -nopw -wait 50 -defer 30 -o /tmp/x11vnc.log &
cd /app
wine explorer /desktop=VMS,1280x720 VMS.exe > /tmp/vms.log 2>&1 &
sleep 60
tail -f /dev/null
