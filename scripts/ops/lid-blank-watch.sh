#!/usr/bin/env bash
# lid-blank-watch — blank all displays when the lid closes (docked).
# Docked lid-close is ignored by logind (HandleLidSwitchDocked=ignore),
# so this only blanks; undocked lid-close still suspends as usual.
# Also blanks tony-dell's greeter display on the shared monitor so it
# doesn't auto-switch inputs when the macbook's signal drops.
DS="org.gnome.Mutter.DisplayConfig"
OP="/org/gnome/Mutter/DisplayConfig"
set_ps() { busctl --user set-property "$DS" "$OP" "$DS" PowerSaveMode i "$1" >/dev/null 2>&1; }
dell_dpms() {
  ssh -o ConnectTimeout=5 -o BatchMode=yes tony-dell \
    'A=$(sudo -n find /run/user/60578 -maxdepth 1 -name ".mutter-Xwaylandauth.*" 2>/dev/null | head -1); sudo -n sh -c "DISPLAY=:1 XAUTHORITY=$A xset dpms force '$1'"' \
    >/dev/null 2>&1 &
}
last=""
while :; do
  st=$(grep -oE "open|closed" /proc/acpi/button/lid/LID0/state 2>/dev/null)
  if [ "$st" = "closed" ] && [ "$last" != "closed" ]; then set_ps 3; dell_dpms off
  elif [ "$st" = "open" ] && [ "$last" = "closed" ]; then set_ps 0; dell_dpms on
  fi
  last=$st
  sleep 2
done
