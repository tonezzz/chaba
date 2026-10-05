# dispatch outcome — traffic camera integration (traffic-snap)

## What was done

Built `traffic-snap`, an HTTP snapshot shim for public Thai traffic
cameras that speaks the **same contract as `vms-snap`** (the XMEye CCTV
shim): `GET /health`, `GET /channels`, `GET /search?q=`, and
`GET /snap?ch=<name>[&fresh=1]` → `image/jpeg`. Any consumer that already
fetches a CCTV frame via `/snap?ch=` can fetch a traffic cam identically.

Camera sources, in `ch` resolution order:

1. **Registry** (`frigate/cameras.json` SSOT, `CAMERAS_JSON` override):
   every enabled non-local cam — DOH/iTIC HLS playlists snapped via
   `ffmpeg -frames:v 1` with `alt_urls` failover, RTSP via ffmpeg, or
   direct `jpeg_url` GET. 33 cams loaded in the worktree registry.
2. **Longdo feed** (`camera.longdo.com/feed/?command=json`, ~190 cams):
   `longdo:<camid>` or title-substring resolution; imgurl jpeg → mjpeg
   first-frame → hls ffmpeg fallback — ported from ada-pi's
   `backend/traffic_camera.py`, including the dead-cam stub heuristic
   (<8KB jpeg = "No sengnal"/not-found stub).

15s per-cam frame cache (`fresh=1` bypasses), ffmpeg semaphore (4),
response headers `X-Camera`/`X-Camera-Source`/`X-Camera-Title`
(percent-encoded — Thai titles crash latin-1 headers, bug found and fixed
during live test)/`X-Cache`/`X-Frame-Age`. 404s return `did_you_mean`
suggestions.

## Premise correction — chaba0

The task says previous implementation lives in "the chaba0 repository".
Verified by cloning `github.com/tonezzz/chaba0` (archived) and grepping:
**chaba0 contains no camera/traffic-cam code** — only unrelated network
"traffic" and a photo-capture UI. The real lineage is in this repo and
ada-pi: `stacks/web/public/cameras.json` → `frigate/cameras.json`
registry (DOH/iTIC/Longdo/Windy URLs already curated) →
`cam-wall-pull.py` (hls/jpeg/youtube pull kinds, traffic/burapha/chonburi
zones) → ada-pi `traffic_camera.py` (now `ada_camera_snapshot
source=traffic`). The missing piece was the on-demand HTTP shim — that's
what was built. Documented in the stack README.

## Where

- `stacks/services/traffic-cam/traffic-snap.py` (new)
- `stacks/services/traffic-cam/{traffic-snap.service,install.sh,verify.sh,README.md}` (new)
- `docs/ssot/jobs/infrastructure/2026-10-05-traffic-cam-snap.yml` (new job trail)
- `docs/ssot/apps/ssot.apps.camwall.yml` (implementation map: Traffic shim)

## Verify

Local run on `127.0.0.1:18378` (test only, not installed):

- `/health` → `{"ok": true, "cameras": 33}`
- `/snap?ch=itic_pracha` → 200, 704×576 live JPEG — OSD "CHARLIE
  CCTV_PRACHANIWET1_92", timestamped 05-10-2026 (verified visually)
- `/snap?ch=longdo:ITICM_BMAMI0081` → 200, 320×240 jpeg (feed path)
- Repeat snap → `X-Cache: hit`; unknown name → 404 + suggestions;
  `/search?q=bangna` → ranked registry+feed matches
- `py_compile` + `bash -n` clean; `ssot-validate-all.mjs` 0 errors

To deploy (explicit approval required — not done in dispatch mode):
`stacks/services/traffic-cam/install.sh` → binds `<tailscale-ip>:8378`,
user unit, registry pointed at the live checkout.

## Notes / not done

- DOH upstream `180.180.242.207:1935` was connection-refused during
  testing (direct `camerai1.iticfoundation.org/hls/` cams unaffected) —
  `alt_urls` failover is the designed mitigation; keep them populated.
- Ada-side wiring (`ada_camera_snapshot source=traffic` → this shim) is
  an ada-pi change; documented in the README as a follow-up, not made
  from a chaba worktree.
- No deploy, no push, no live-checkout edits — per dispatch rules.
