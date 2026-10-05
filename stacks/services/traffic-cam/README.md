# traffic-cam — on-demand traffic camera snapshots

HTTP shim that serves **live still frames** from public Thai traffic
cameras through the same endpoint contract as `vms-snap` (the XMEye CCTV
shim on mn01 :8377). Any consumer that already does
`GET /snap?ch=<name>` → JPEG/PNG can fetch a traffic cam exactly like a
CCTV cam — no display, no Wine, everything is a plain HTTP fetch or an
ffmpeg frame-grab.

```
GET /health                   -> {"ok": true, "cameras": 33}
GET /channels                 -> registry camera map (name -> meta)
GET /search?q=<query>         -> ranked matches (registry + Longdo feed)
GET /snap?ch=<name>[&fresh=1] -> 200 image/jpeg   (X-Camera, X-Camera-Source,
                                  X-Camera-Title, X-Cache, X-Frame-Age hdrs)
```

`ch` resolves: registry name → registry title/camid substring →
`longdo:<camid>` → Longdo feed title substring. Unknown names get a 404
with `did_you_mean` suggestions. A 15s per-camera cache (fresh=1 bypasses)
keeps bursts from spawning one ffmpeg per request.

## Camera sources

| source | URLs | used for |
|---|---|---|
| DOH (Dept. of Highways) Wowza | `http://180.180.242.207:1935/<Phase>/<PER_x_yyy[_IN|_OUT]>.stream/playlist.m3u8`, same on `…242.208` | national highway cams — hls_url in `frigate/cameras.json` |
| iTIC proxy for DOH | `https://camerai1.iticfoundation.org/pass/<ip>:1935/<path>` | TLS-wrapped mirror of the DOH playlists — registry `alt_urls` |
| DOH alternate CDN | `https://streaming1/2.highwaytraffic.go.th/<path>` | second set of `alt_urls` |
| iTIC direct | `https://camera1.iticfoundation.org/hls/<cam>.m3u8`, `…/camerai1…` | iTIC Bangkok/provincial cams |
| iTIC stills | `https://camera1.iticfoundation.org/jpeg2.php?camid=<ip:port>` | instant JPEG (used by the rama9 wall zone; registry `jpeg_url`) |
| Longdo feed | `https://camera.longdo.com/feed/?command=json` | ~190 Thai cams: `camid`, Thai `title`, `imgurl` (jpeg still), `vdourl` (mjpeg), `hls_url`; suspended cams carry `X.X.X.X`/`tempsus` placeholders |
| Windy webcams | `https://api.windy.com/webcams/api/v3/webcams` (key in cameras.json `sources.windy`) | registry enrichment only (`windy_id`); not fetched by the shim |

Registry = `frigate/cameras.json` (generated from
`stacks/web/public/cameras.json` — "Single source of truth for all
cameras"). `CAMERAS_JSON` env / `--cameras-json` overrides. Cams with
`source: local` are skipped (house cams stay on go2rtc/VMS).

Fetch fallbacks: registry hls tries `hls_url` then every `alt_urls`;
longdo tries `imgurl` → `vdourl` mjpeg first-frame → `hls_url`.
Dead-cam stubs (43B "not found", ~3KB "No sengnal" jpeg) are rejected by
an 8KB minimum — the same heuristic as `cam-wall-pull.py` and ada-pi's
`backend/traffic_camera.py` (which this service ports).

## Install

```bash
./install.sh                      # copies to ~/.local/share/traffic-cam/,
                                  # binds <tailscale ip>:8378, user unit
./install.sh --repo /path/to/chaba-checkout   # non-default registry path
./verify.sh                       # /health + /channels + one live snap
```

The unit (`traffic-snap.service`) binds the host's tailscale IP only —
tailnet-reachable from idc01/idc02/ada-pi, not LAN-public. Override with
`TRAFFIC_SNAP_BIND` / `TRAFFIC_SNAP_PORT` env when running by hand.

## Integration points

- **Ada** — ada-pi `backend/traffic_camera.py` does the equivalent fetch
  in-process today; pointing `ada_camera_snapshot(source=traffic)` at this
  shim (`GET /snap?ch=…`) would centralize resolution + caching. Track as
  an ada-pi follow-up, not part of this repo.
- **cam-wall** — `scripts/cam-wall/cam-wall-pull.py` already generates the
  `traffic`/`burapha`/`chonburi` zones from the same registry and keeps
  last-good thumbs; this shim is for *on-demand* snaps, walls keep their
  periodic puller.
- **vms-snap parity** — identical `/health` + `/snap?ch=` surface, so a
  caller can treat `http://<mn01>:8377` (CCTV) and
  `http://<this-host>:8378` (traffic) interchangeably.

## Notes

- `chaba0` (archived predecessor repo) contains no camera code — the
  traffic-cam lineage starts in this repo: cameras.json registry →
  cam-wall-pull hls/jpeg/youtube kinds → ada-pi `traffic_camera` → this
  shim.
- DOH Wowza upstreams refuse connections intermittently (observed
  2026-10-05: `180.180.242.207:1935` refused + the itic `pass/` proxy
  502'd while direct `camerai1 …/hls/` cams stayed live). Multi-URL
  failover is the mitigation — keep `alt_urls` populated.
