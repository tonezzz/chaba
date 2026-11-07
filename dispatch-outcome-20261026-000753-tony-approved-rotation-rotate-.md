# Dispatch outcome — rotate omen RTSP credential (ip_cam_65)

## Status: PARTIALLY DONE — blocked on camera power (needs Tony)

Tony approved the rotation. Everything that can be done without the camera
is done; the camera-side password change and final verification cannot run
because **the camera is off the network**.

## What was verified

- Exposed credential = the `admin` password for the VStarcam C7824WIP at
  `192.168.2.71:10554` (value matched the one documented in SSOT).
- Camera is genuinely offline: absent from a full `nmap -PR` ARP scan of
  192.168.2.0/24 (15 hosts up, MAC d4:9e:3b:6a:94:90 not present),
  `No route to host` on :10554/:80/:443 from both mn01 and tony-omen,
  go2rtc frame endpoint returns 0 bytes.
- Consumers: go2rtc on tony-omen (`go2rtc-omen.service` system unit owns
  :1984/:8554; `go2rtc.service` user unit also active) plus a stale copy
  on tony-dell (service not running). HA reads go2rtc loopback only.
- go2rtc does NOT expand env vars in `exec:` lines (argv passed literally,
  no shell) — verified experimentally — so wrapper scripts are required.

## What changed (live hosts)

**tony-omen**
- `~/.config/secrets/ipcam65.env` created (chmod 600): `IPCAM65_USER`,
  `IPCAM65_PASS` (currently still the OLD password — deliberate, so the
  stream self-heals if the camera returns before rotation runs).
- `~/.config/go2rtc/ip_cam_65_{auto,hd,low}.sh`: source the env file;
  auto.sh keeps its HD→low probe logic; hd/low are new dedicated wrappers.
- `~/.config/go2rtc/go2rtc.yaml`: credential removed entirely (0 hits for
  the host/`admin:`); three exec: lines now call the wrappers. Backup at
  `go2rtc.yaml.bak-rotate-20261026`.
- `~/.config/go2rtc/rotate-ipcam65.sh`: armed rotation runner — probes the
  camera, sets a new 20-char password via VStarcam Hi3510 CGI (:81/:80,
  three endpoint variants), updates ipcam65.env, restarts both go2rtc
  units, verifies new cred accepted + old cred rejected via ffprobe.
  Never prints the credential. `--status` mode for a quick check.
- Both go2rtc units restarted; all 12 streams registered; exec spawn
  verified (ffmpeg launches, fails only on camera-unreachable).

**tony-dell** — same env file + wrappers + sanitized go2rtc.yaml
(service inactive; kept consistent).

## What changed (repo, dispatch branch, not pushed)

- `docs/ssot/infrastructure/ssot.ip-camera.yml` — plaintext password
  scrubbed; secret location, wrappers, rotation runner, camera-offline
  status, and dead camera-monitor.service drift documented.
- `docs/ssot/jobs/infrastructure/2026-10-26-ipcam65-rtsp-rotation.yml` —
  full runbook (done / pending / residual risks / verify).
- `scripts/rotate-ipcam65-credential.sh` — repo copy of the live script.
- Commit `40d16c3d` on `dispatch/20261026-000753-…` (pre-commit hooks
  passed; not pushed).

## What remains (needs Tony)

The camera (Coffee Corner VStarcam) must be powered on / reconnected.
Then finish is one command on tony-omen:

    ~/.config/go2rtc/rotate-ipcam65.sh

Board request `ip-cam-65-192-168-2-71-is-powered-off-of-8e9256` raised;
`needs-input.txt` written to the task dir. After it runs, copy the
updated ipcam65.env to tony-dell and close the card.

## Residual risks (noted in job yml)

- Password still transits ffmpeg argv while streaming (original exposure
  vector) — hiding it needs a concat-playlist input; unverifiable while
  the camera is down. Follow-up card candidate.
- Same admin/tonytony password configured for a *different* camera at
  192.168.1.41 (michael-home) in frigate configs — same exposure logic,
  separate rotation card recommended.
- `camera-monitor.service` no longer exists on omen/mn01 and is inactive
  on dell — documented auto-restart monitoring is dead everywhere.
