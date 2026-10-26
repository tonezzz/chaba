# Dispatch outcome — rotate omen RTSP credential (ip_cam_65), session 2

## Status: STAGED + AUTO-FINISHER ARMED — camera still off-network

Continuation of dispatch-20261026-000753 (which did all consumer-side
staging). Tony answered "proceed" to the camera-power request at 08:22
+07; this session re-verified at ~09:05 +07 that **the camera is still
off the network** and closed the loop by arming an automatic finisher.

## Re-verified this session

- Camera `192.168.2.71` (MAC d4:9e:3b:6a:94:90): absent from a fresh
  `nmap -PR` ARP scan of 192.168.2.0/24 on tony-omen (18 hosts up), AND
  a subnet-wide port scan found no host with :10554/:81/:80 open — so
  the camera did not simply DHCP to a new IP. Unreachable from mn01 too.
- Prior staging intact on both hosts: `~/.config/secrets/ipcam65.env`
  (600) on tony-omen + tony-dell, three `ip_cam_65_*.sh` exec wrappers,
  go2rtc.yaml sanitized (0 hits for camera IP / credentials), both omen
  go2rtc units `active`, 12 streams registered (camera streams present
  but will keep failing until the cam returns — expected).

## What changed this session

**tony-omen (live)**
- `~/.config/go2rtc/ipcam65-rotate-finisher.sh` — wrapper that probes
  the camera, runs the approved `rotate-ipcam65.sh` when :10554 answers,
  scp's the rotated env to tony-dell, posts the result to the card, and
  disables itself. Self-disables + reports on definitive failure
  (rc 3/4/5/6) too. 14-day expiry. flock-guarded, never prints creds.
- `~/.config/systemd/user/ipcam65-rotate-finish.{service,timer}` —
  enabled, every 3 min (linger already on). First tick verified:
  fired, cam unreachable, clean exit 0, timer re-armed.

**repo (dispatch branch, commit 58dfb6f4)**
- `scripts/ipcam65-rotate-finisher.sh`, `systemd/ipcam65-rotate-finish.*`
- `docs/ssot/jobs/infrastructure/2026-10-26-ipcam65-rtsp-rotation.yml`
  updated: status `staged-auto-finish-armed`, finisher documented.

## Net effect

Nothing left is blocked on a session. When the Coffee Corner camera is
powered on, the approved rotation completes unattended within ~3 min:
new 20-char password set on the camera via Hi3510 CGI, old credential
verified rejected, `ipcam65.env` updated on omen + synced to dell,
go2rtc restarted, frame endpoint verified, result posted to the card.

## To verify (once camera is powered)

- Card comms will carry `ROTATION COMPLETE (auto-finisher)` — or a
  failure line if the CGI variants don't take.
- `ssh tony-omen '~/.config/go2rtc/rotate-ipcam65.sh --status'` →
  `camera: reachable` / `stored cred: ACCEPTED`
- `ssh tony-omen 'curl -s -o /dev/null -w "%{http_code} %{size_download}" \
   http://127.0.0.1:1984/api/frame.jpeg?src=ip_cam_65_low'` → 200 + bytes

## Still needs Tony (unchanged)

Physically power / rejoin the Coffee Corner VStarcam to Wi-Fi. No board
request re-raised — the prior one was already answered "proceed"; the
finisher covers the completion path, and a fresh request would just
duplicate the ask.
