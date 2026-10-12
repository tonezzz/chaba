# Host Camera Onboard (host webcam → go2rtc → tony-ha)

Standard procedure for exposing a host's built-in/USB webcam as `camera.<host>_cam` in tony-ha, and as a go2rtc stream usable by cctv walls / cast-cam / Ada.

Proven on tony-omen 2026-10-11. See `ssot.ip-camera.yml` "Omen Webcam" section for the live example.

## Prereqs

- Host reachable over the ssh mesh (`ssh <host>` BatchMode works).
- `sudo -n` on the host (for system unit + group change), or use pkexec interactively.
- A `/dev/videoN` node on the host. If absent, the camera is a driver/enumeration problem — onboard is blocked (see "MacBook note" below).

## Steps

1. **Video access**: ensure the streaming user can open `/dev/video0`.
   `sudo usermod -aG video tony` — note: pre-existing user-manager sessions keep stale groups; use a **system** unit with `User=tony` + `SupplementaryGroups=video` so group resolution is fresh each start.

2. **Verify the sensor**:
   `ffmpeg -f v4l2 -list_formats all -i /dev/video0` (pick a supported `-input_format` + `-video_size`), then
   `ffmpeg -f v4l2 -input_format mjpeg -video_size 640x480 -i /dev/video0 -frames:v 1 /tmp/cam.jpg`.

3. **Run go2rtc on the source host** (do NOT use `exec:ssh …` producers on the aggregator — they die with `exec/pipe: EOF`; local exec works). Copy `~/.local/bin/go2rtc` from tony-dell, minimal config:

   ```yaml
   api:   { listen: ":1984" }
   rtsp:  { listen: ":8554" }
   streams:
     omen_cam:            # rename per host
       - exec:ffmpeg -nostdin -hide_banner -f v4l2 -input_format mjpeg -video_size 640x480 -i /dev/video0 -c:v libx264 -preset ultrafast -tune zerolatency -pix_fmt yuv420p -an -f mpegts -
   ```

   System unit `go2rtc-<host>.service` (User=tony, SupplementaryGroups=video, Restart=always). Verify `http://<host>:1984/api/frame.jpeg?src=<host>_cam` → 200 JPEG.

4. **Aggregator relay (tony-dell go2rtc)**: add to `streams:` in `~/.config/go2rtc/go2rtc.yaml` (4-space indent):

   ```yaml
       <host>_cam:
           - ffmpeg:rtsp://<tailnet-ip>:8554/<host>_cam#video=h264
   ```

   `systemctl --user restart go2rtc` (PATCH /api/config does NOT reliably register new streams — restart does). Verify `http://127.0.0.1:1984/api/frame.jpeg?src=<host>_cam` → 200.

5. **HA entity**: append to `camera:` in `/home/tony/.config/home-assistant/configuration.yaml`:

   ```yaml
     - platform: ffmpeg
       name: <host>_cam
       input: -i http://<tailnet-ip>:1984/api/frame.jpeg?src=<host>_cam
   ```

   `docker restart tony-ha`, wait ~60s, verify `/api/states/camera.<host>_cam` exists and `camera_proxy` returns 200.

   Why the jpeg URL (not rtsp): ffmpeg camera snapshots double as the dashboard still; a jpeg fetch is instant while an rtsp connect pays the source's exec cold-start (~15–20 s) and timed out camera_proxy. The `generic` platform no longer accepts YAML config — use `ffmpeg`.

## Gotchas (hit for real on omen, 2026-10-11)

- `-listen 1` ffmpeg MJPEG servers are one-shot-per-connection → crash-loops; don't use for HA.
- RTSP **publish to** dell's go2rtc is not accepted.
- `-nostdin` is mandatory on any exec'd ffmpeg (stdin EOF kills it).
- `-c:v copy` of mjpeg into mpegts muxes as "private data stream" — unreadable; always transcode to h264.
- Dell `rtsp://127.0.0.1:8554/<host>_cam` re-serve returned "Invalid data" to direct consumers — HA reads the jpeg endpoint instead.

## MacBook note

tony-macbook's FaceTime HD (PCIe `14e4:1570`) does not enumerate in `lspci` on Linux → no `/dev/video*`. Steps 1-2 fail.

Resolved 2026-10-12: the chip is **not on the PCI fabric at all** — a full `pci rescan` (all buses re-enumerated, kernel `busn_res` reconfig logged) produced no `1570`; device count unchanged. On 2016 Touch Bar models (13,3) the camera is routed through the Apple **T1 / iBridge**, for which Linux has no camera path — the `facetimehd` (bcwc_pcie) driver only applies to pre-T1 models where `1570` actually enumerates. Built-in cam on this host is a dead end; use a USB webcam or phone-as-cam instead (the `gesture-control-rebuild` design already uses iPhone as the camera node).
