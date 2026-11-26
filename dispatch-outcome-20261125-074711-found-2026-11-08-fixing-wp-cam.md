# Dispatch outcome — go2rtc-empty-frames-all-cams (2026-11-25)

## What was found

The card's premise was half stale. **tony-dell has no go2rtc at all** —
`go2rtc.service` is `.parked` there and nothing listens on :1984. go2rtc
moved dell → omen; `job:wp-cam-snapshot` on dell is declared with
`GO2RTC_URL=http://tony-omen.taila0626a.ts.net:1984` (ssot.jobs.yml). The
"127.0.0.1:1984 / 8/8 empty frame" signature was the pre-move state.

On **tony-omen** (where go2rtc actually lives, `go2rtc-omen.service`,
up 1d12h since the Nov-23 reboot) every stream was wedged:
`/api/frame.jpeg?src=omen_cam` hung >100 s with no response even though
its ffmpeg v4l2 producer kept writing ~456 MB of mpegts into the pipe —
the producer pipeline was transport-alive but never emitted a frame.
Other streams returned 200/0 B.

## What was done

- `systemctl restart go2rtc-omen.service` on tony-omen (07:59 +07).
- Verified `omen_cam` frame.jpeg returns a valid 640×480 JPEG (~30 KB)
  in ~1 s — locally on omen AND from tony-dell through the tailnet URL
  the snapshot job actually uses.
- cam-wall/cam-snapshot consumers on omen recover on their next poll.

## Result / remaining blockers (all upstream of go2rtc, not fixable from here)

- **6 xiaomi streams** (c100/c201 + h264/hd/hd_h264 variants): 200/0 B.
  `xiaomi-token-refresh.service` FAILED 2026-11-25 00:00 — "no valid
  passToken cookie". **Needs Tony to re-login to account.xiaomi.com in
  Chrome on omen**; the refresh job then re-patches go2rtc.yaml.
- **ip_cam_65** (+variants): camera 192.168.2.71 still off-network (no
  route to host; absent from ARP since the Oct-26 credential rotation;
  the `ipcam65-rotate-finish` auto-finisher expired ~Nov 9).
- **wp-cam-snapshot on dell is masked** (service → /dev/null, timer dead
  since Nov 24 08:04, right after the last 8/8-FAIL run). No host runs
  the job now — WP cam snapshots are off fleet-wide. Left masked
  deliberately: with 7/8 cams still failing, a partial-ok run exits 0
  and would hide the breakage from timer-sentinel. Re-enable decision
  belongs to the card owner once upstreams recover.
- Housekeeping noted (not changed): duplicate user-unit `go2rtc.service`
  idles alongside `go2rtc-omen.service` on omen; a stray HA-spawned
  `/bin/go2rtc` test instance listens on 127.0.0.1:18554 / *:18555.

## Deliverables

- `docs/ssot/jobs/infrastructure/2026-11-25-go2rtc-empty-frames-dell-omen-diagnosis.yml`
  — full diagnosis record with verify commands.
- Card comms posted on `go2rtc-empty-frames-all-cams` (this card) and
  `go2rtc-7-camera-producers-return-empty-f-cc9176` (omen producers).

## How to verify

```
ssh tony-omen 'curl -s -o /tmp/x.jpg -w "%{size_download}\n" \
  "http://127.0.0.1:1984/api/frame.jpeg?src=omen_cam"'   # ~30000
ssh tony-dell 'curl -s -o /tmp/x.jpg -w "%{size_download}\n" \
  "http://tony-omen.taila0626a.ts.net:1984/api/frame.jpeg?src=omen_cam"'
```

Both return a ~30 KB JPEG. `journalctl -u go2rtc-omen.service` on omen
shows producer errors only for the upstream-dead streams.

lessons:
- go2rtc exec producers can stay transport-alive (ffmpeg writing to the
  pipe for days) while go2rtc never emits a frame — frame.jpeg hanging
  >30 s, not returning 0B, is the signature of a wedged producer
  pipeline; `systemctl restart` is the fix, and it's safe when all
  consumers already get nothing.
- Verify "which host actually runs X" before trusting a card's host
  field — this card said tony-dell but go2rtc and its config live on
  tony-omen; ssot.jobs.yml env (GO2RTC_URL) is the truth, not the card
  title.
- go2rtc `/api/streams` lists producers but not liveness — a stream
  with a running producer can still serve nothing; probe
  `/api/frame.jpeg` per stream to know real state.
- Masked-then-parked systemd units on job hosts are deliberate state —
  check `ls -la` for `.parked` siblings and journal timing before
  assuming a "dead" job is an oversight.
