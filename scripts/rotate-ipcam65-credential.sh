#!/bin/bash
# rotate-ipcam65.sh — rotate the VStarcam C7824WIP (ip_cam_65, 192.168.2.71) RTSP credential.
# Steps: probe camera -> set new password on camera via Hi3510 CGI -> update
# ~/.config/secrets/ipcam65.env -> restart go2rtc units -> verify new accepted + old rejected.
# NEVER prints the credential. Usage: rotate-ipcam65.sh [--status]
set -u
CAM=192.168.2.71
ENV=/home/tony/.config/secrets/ipcam65.env
. "$ENV" || { echo "FAIL: cannot read $ENV"; exit 1; }
OLD="$IPCAM65_PASS"; USER="${IPCAM65_USER:-admin}"

rtsp_probe() { # $1=user $2=pass $3=path -> 0 if stream opens
  ffprobe -v quiet -rtsp_transport tcp -timeout 5000000 -i "rtsp://$1:$2@$CAM:10554/udp/$3" >/dev/null 2>&1
}
cam_up() { timeout 3 bash -c "echo > /dev/tcp/$CAM/10554" 2>/dev/null; }

if [ "${1:-}" = "--status" ]; then
  cam_up && echo "camera: reachable" || echo "camera: UNREACHABLE"
  cam_up && { rtsp_probe "$USER" "$OLD" av0_1 && echo "stored cred: ACCEPTED" || echo "stored cred: rejected"; }
  exit 0
fi

cam_up || { echo "FAIL: $CAM:10554 unreachable (camera off-network) - power it on and re-run"; exit 2; }
rtsp_probe "$USER" "$OLD" av0_1 || { echo "FAIL: stored credential already rejected by camera - investigate before rotating"; exit 3; }
echo "camera reachable, current credential valid"

NEW="$(tr -dc a-zA-Z0-9 < /dev/urandom | head -c 20)"
echo "generated new credential (20 chars)"

# VStarcam Hi3510 CGI - try known setuserattr variants on ports 81 and 80.
CHANGED=0
for PORT in 81 80; do
  for Q in \
    "cmd=setuserattr&-username=$USER&-newname=$USER&-password=$NEW" \
    "cmd=setuserattr&-username=$USER&-password=$NEW" \
    "cmd=setuser&-name=$USER&-pwd=$NEW"; do
    CODE=$(curl -s -o /dev/null -w "%{http_code}" --anyauth -u "$USER:$OLD" -m 8 \
      "http://$CAM:$PORT/cgi-bin/hi3510/param.cgi?$Q")
    [ "$CODE" = "200" ] && { echo "CGI accepted on :$PORT ($Q variant ${Q%%&*})"; CHANGED=1; break 2; }
  done
done
[ "$CHANGED" = 1 ] || { echo "FAIL: no CGI endpoint accepted the password change"; exit 4; }

sleep 2
rtsp_probe "$USER" "$NEW" av0_1 || { echo "FAIL: camera did not start accepting new credential"; exit 5; }
echo "new credential ACCEPTED by camera"
rtsp_probe "$USER" "$OLD" av0_1 && { echo "WARN: old credential still accepted - rotation incomplete"; exit 6; }
echo "old credential REJECTED by camera"

sed -i "s/^IPCAM65_PASS=.*/IPCAM65_PASS=$NEW/" "$ENV"
chmod 600 "$ENV"
echo "env file updated"

systemctl --user restart go2rtc.service && echo "user go2rtc.service restarted"
if sudo -n systemctl restart go2rtc-omen.service 2>/dev/null; then
  echo "system go2rtc-omen.service restarted"
else
  echo "NOTE: go2rtc-omen.service needs manual restart (sudo)"
fi
sleep 3
curl -s -m15 -o /dev/null -w "go2rtc ip_cam_65_low frame: HTTP %{http_code} %{size_download}B\n" \
  "http://127.0.0.1:1984/api/frame.jpeg?src=ip_cam_65_low"
echo "ROTATION COMPLETE"
