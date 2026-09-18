#!/usr/bin/env bash
# Keep tony-dell's physical seat on vt7 (Xorg :1 / LXQt) whenever lxqt-seat
# is running. Steals the foreground back from GDM's Wayland greeter or a
# bare getty, but never yanks away a real logged-in graphical session.
set -u

SEAT_VT=7

systemctl --user is-active --quiet lxqt-seat.service || exit 0
[ -S /tmp/.X11-unix/X1 ] || exit 0

active="$(cat /sys/class/tty/tty0/active)"
[ "$active" = "tty$SEAT_VT" ] && exit 0
vt_nr="${active#tty}"
case "$vt_nr" in (*[!0-9]*|'') exit 0;; esac

# Respect a real user session occupying the foreground VT.
for s in $(loginctl list-sessions --no-legend --no-pager 2>/dev/null | awk '{print $1}'); do
    [ "$(loginctl show-session "$s" -p VTNr --value 2>/dev/null)" = "$vt_nr" ] || continue
    [ "$(loginctl show-session "$s" -p Class --value 2>/dev/null)" = "greeter" ] && continue
    case "$(loginctl show-session "$s" -p Type --value 2>/dev/null)" in
        x11|wayland|mir|tty) exit 0 ;;
    esac
done

if sudo -n chvt "$SEAT_VT"; then
    echo "barrier-pin-vt: switched $active -> tty$SEAT_VT"
fi
