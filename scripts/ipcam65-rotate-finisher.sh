#!/bin/bash
# ipcam65-rotate-finisher.sh — completes the APPROVED ip_cam_65 RTSP rotation
# once camera 192.168.2.71 rejoins the network. Runs under
# ipcam65-rotate-finish.timer on tony-omen (systemd --user).
# On success/definitive-failure/expiry it posts to the board and disables
# itself. Never prints credential values.
set -u
CAM=192.168.2.71
DIR="$HOME/.config/go2rtc"
MARKER="$DIR/.ipcam65-rotated"
DONE="$DIR/.ipcam65-rotate-finisher-done"
ARMED="$DIR/.ipcam65-rotate-armed"
CARD=rotate-omen-rtsp-credential-exposed-in-d-596eaa
BOARD=https://idc03.taila0626a.ts.net:10000/comment

say() { # $1 = text (sanitised for JSON)
  local t; t=$(printf '%s' "$1" | tr -d '"\\' | head -c 400)
  curl -s -m10 -X POST "$BOARD" -H 'Content-Type: application/json' \
    -d "{\"id\":\"$CARD\",\"from\":\"devin\",\"text\":\"$t\"}" >/dev/null 2>&1 || true
}
stop() { systemctl --user disable --now ipcam65-rotate-finish.timer >/dev/null 2>&1; touch "$DONE"; }

exec 9>"$DIR/.ipcam65-finisher.lock"; flock -n 9 || exit 0
[ -f "$DONE" ] && exit 0
[ -f "$MARKER" ] && { stop; exit 0; }

# Expiry: give up after 14 days armed so a dead camera does not leave an
# always-on credential rotator.
if [ -f "$ARMED" ] && [ -n "$(find "$ARMED" -mtime +14 2>/dev/null)" ]; then
  stop
  say "ipcam65 rotation finisher EXPIRED after 14d - camera never rejoined. Re-arm by deleting $DONE and re-enabling ipcam65-rotate-finish.timer if still wanted."
  exit 0
fi

timeout 3 bash -c "echo > /dev/tcp/$CAM/10554" 2>/dev/null || exit 0   # still off-network; next tick

OUT=$("$DIR/rotate-ipcam65.sh" 2>&1); RC=$?

case $RC in
  0)
    if scp -o BatchMode=yes -q "$HOME/.config/secrets/ipcam65.env" \
        tony-dell:.config/secrets/ipcam65.env 2>/dev/null; then
      SYNC="tony-dell env synced"
    else
      SYNC="WARN: tony-dell env sync failed - copy ipcam65.env manually"
    fi
    touch "$MARKER"; stop
    say "ROTATION COMPLETE (auto-finisher): camera accepted NEW credential, OLD credential rejected, ipcam65.env updated on tony-omen, $SYNC, go2rtc restarted, stream verified. Verify: ~/.config/go2rtc/rotate-ipcam65.sh --status"
    ;;
  2) : ;;                                        # camera dropped mid-run; retry next tick
  *) stop; say "ROTATION FINISHER FAILED rc=$RC - auto-disabled, no retry. Last line: $(echo "$OUT" | tail -1). Manual check on tony-omen: ~/.config/go2rtc/rotate-ipcam65.sh --status" ;;
esac
