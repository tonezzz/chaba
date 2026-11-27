# Dispatch outcome — go2rtc camera producers on tony-omen

Card: `go2rtc-7-camera-producers-return-empty-f-cc9176`
Date: 2026-11-27

## Result

**Done-condition NOT met — and cannot be met remotely.** All three
remaining cameras are physically off the network (L2/ARP-absent), so
`frame.jpeg` still returns 200/0B for `ip_cam_65`, `xiaomi_c100*` and
`xiaomi_c201*`. `omen_cam` remains healthy (~30KB JPEG). Producer configs
were inspected and corrected where correction was possible; the recurring
root cause (DHCP IP churn) now has a self-healing fix deployed.

## What was found

- **passToken is VALID** — correcting the 2026-11-25 diagnosis. go2rtc's
  cloud auth works: `GET /api/xiaomi?id=6891138643&region=sg` on omen
  returns both cameras. The dead `xiaomi-token-refresh` job only means the
  Chrome-cookie refresh path is dead (omen Chrome has zero
  account.xiaomi.com cookies); the yaml token itself authenticates fine.
- **All 3 cameras offline at L2**: full ping/ARP sweep of
  192.168.2.0/24 (eno1) and 192.168.0.0/24 (wlo1) from omen finds neither
  camera MAC — c100 `b8:88:80:cb:7d:2c`, c201 `d8:3a:36:7d:10:0d`; ip_cam_65's
  reserved .71 is ARP INCOMPLETE. Cloud `localip` values are stale
  (c100->.92 is now a different device; c201->.77 ARP-dead).
- **Root cause of recurring breakage**: go2rtc xiaomi producers dial the
  camera directly over UDP (tutk:32761 / cs2:32108) — the URL IP must be
  current. Cameras are DHCP floaters (c100 seen at .72/.73/.74/.79/.81/.92);
  hardcoded IPs guarantee recurring 0B.
- **Bug found**: `xiaomi-token-refresh.py` restarted `systemctl --user
  restart go2rtc` — the degraded user unit that cannot bind :1984 — so a
  successful token patch would never reach the live `go2rtc-omen.service`.

## What changed

On **tony-omen** (`~/.config/go2rtc/`):

- **NEW `xiaomi-cam-resolve.py`** — parses `xiaomi://user:region@IP?did=`
  producers from go2rtc.yaml, queries the running instance's
  `/api/xiaomi` device list (did→ip+mac), verifies IP by ARP MAC match
  with a throttled (≥15 min) /24 ping-sweep fallback, rewrites the yaml
  and POSTs `/api/restart` on change. Offline cameras keep last IP.
- **NEW units** `xiaomi-cam-resolve.{service,timer}` (every 5min),
  rendered from ssot.jobs.yml via `scripts/render-jobs.py`, enabled.
  First timer run exit 0; dry-run verified correct offline detection.
- **FIXED `xiaomi-token-refresh.py`** — now restarts
  `sudo -n systemctl restart go2rtc-omen.service` (the :1984 owner),
  then best-effort the user unit.

In **this worktree** (chaba):

- `docs/ssot/infrastructure/ssot.jobs.yml` — added `xiaomi-cam-resolve`
  job; marked `xiaomi-token-refresh` `enabled: false` (units were
  deliberately retired on-host 2026-11-26; re-arm only after Tony
  re-logs into account.xiaomi.com in omen Chrome).
- `docs/ssot/generated/jobs.*.yml` — regenerated catalog (also picked up
  pre-existing drift: retry-storm-watch, telemetry-ha-push-ada,
  job-health-sweep, litellm-budget-watch).
- `systemd/generated/tony_omen/xiaomi-cam-resolve.{service,timer}` —
  rendered units.
- `docs/ssot/jobs/infrastructure/2026-11-27-go2rtc-xiaomi-cam-ip-resolver.yml`
  — full job trail.

## How to verify

- `ssh tony-omen 'curl -s -o /tmp/x.jpg -w "%{size_download}\n"
  "http://127.0.0.1:1984/api/frame.jpeg?src=omen_cam"'` → ~30000
- `ssh tony-omen 'journalctl --user -u xiaomi-cam-resolve.service -n 20'`
- `ssh tony-omen 'curl -s "http://127.0.0.1:1984/api/xiaomi?id=6891138643&region=sg"'`
- Camera presence: ping-sweep 192.168.2.0/24 on omen, grep
  `b8:88:80|d8:3a:36` in `ip neigh` — absent = offline.

## Needed from Tony

Physical check of the three cameras (power/WiFi — all three down at once
suggests a shared cause like a power strip or AP). Optional durable fix:
DHCP reservations on the ZTE F688 for the camera MACs. Board request
raised on the card.

lessons:
- go2rtc xiaomi:// producers need the camera's CURRENT LAN IP — they dial
  UDP direct (tutk:32761/cs2:32108), no relay; DHCP-floaters need an
  IP-resolver, not a static yaml entry.
- Two go2rtc units on omen: system go2rtc-omen.service owns :1984;
  user go2rtc.service is degraded (can't bind). Token refresh must
  restart the system unit.
- The yaml passToken can be valid even when the Chrome-cookie refresh
  job fails — check `GET /api/xiaomi?id=<uid>&region=<region>` before
  declaring the token dead.
- Cloud `localip` in Xiaomi device_list goes stale when a camera is
  offline — verify by ARP MAC before trusting it.
- This LAN has heavy DHCP/IP churn (repeaters, private MACs) — ARP views
  differ per host; resolve devices by MAC, never by IP alone.
