# gesture-control-rebuild — ada_v2 hand-gesture UI rebuilt as two-page app + WS relay

## What changed (all committed on `dispatch/20261009-133455-...`, commit 926fb20e)

- **`stacks/tony-dell/gesture-relay/`** (new quadlet, gev-gemini shape):
  `relay.py` asyncio websockets fan-out on :8794 — `?role=controller`
  emits, `?role=screen` receives, `{type:"peer",...}` presence events both
  ways, `GET /health` on the same port via the ws `process_request` hook.
  `gesture-relay.container` publishes on the tailnet IP only
  (`install.sh` renders `PublishPort=<tailscale-ip>:8794:8794` — xmeye
  pattern); `requirements.txt` pins websockets 16.1.1; `live-check.py`
  smoke-covers health + fan-out.
- **`stacks/web/public/apps/gesture/index.html`** — iPhone controller:
  `getUserMedia(facingMode:"environment")` → hidden video → rAF →
  MediaPipe HandLandmarker (`numHands:1`, VIDEO, GPU) using the vendored
  `/apps/vendor/mediapipe/vision_bundle.mjs` + wasm; model
  `hand_landmarker.task` (7.8MB) vendored into the same dir — no CDN.
  Live preview + cyan HAND_CONNECTIONS skeleton + big status line +
  "Send test pinch". Emits raw normalized `{type:"gesture",x,y,wx,wy}`
  ~20Hz (X mirror-flipped) + `action` edges: `pinch` (dist lm4–lm8 <0.05,
  rising edge), `fist_start`/`fist_end` (4 finger tips closer to wrist
  than MCPs, thumb not counted).
- **`stacks/web/public/apps/gesture/screen.html`** — TV/display surface:
  fullscreen dark page, 8 demo counter tiles, 2 fist-draggable windows,
  CAST TO TV window (`GET /apps/yolo/api/tvs` populates the dropdown,
  `/apps/yolo/api/cast?target=…` casts via the mn01 yolo service → HA
  `play_media`). Cursor = ada_v2 cyan 24px ring, z-top,
  pointer-events-none. Screen-side pipeline per the KB constants:
  SENSITIVITY 2.0 → clamp → LERP 0.2 → snap 50px / release 100px
  hysteresis with cyan glow; pinch → `elementFromPoint().closest('button,a,[role=button]').click()`;
  fist → hit-test `.gwin` rects, wrist-delta drag (0.5px deadzone,
  viewport clamped).
- **Routes**: `ssot.routes.yml` gained `gesture-relay` service +
  `gesture-live` (proxy, ws, `custom`) and `gesture` (static, `custom`)
  routes; `render-routes.py` got matching `CUSTOM_BLOCKS`;
  `Caddyfile.generated` + committed `Caddyfile` synced (only remaining
  delta vs generated = pre-existing yt-cache/yt-corpus hunk);
  `routes.json` regenerated (51 routes). `/apps/gesture/screen` serves
  `screen.html` via a `rewrite` so the spec URL returns 200 directly.
- **chaba-home (tony-ha)**: new "Gesture" panel tab pushed live at
  position 2 — right after Chat — via `push-dashboard.py` websocket
  mutate: markdown explainer + weblinks to `/apps/gesture/` and
  `/apps/gesture/screen`. Repo snapshot `chaba-home-current.json` synced;
  dashboards SSOT annotated.
- **Trail**: `docs/ssot/jobs/gesture/2026-10-09-gesture-two-page-rebuild.yml`.

## Verified (this session, local end-to-end)

- relay: `GET /health` → 200 `{ok,controllers,screens}`; controller→screen
  fan-out + peer events; `live-check.py` PASS.
- playlive headless browser opened the screen page: ws connected, a
  simulated controller ws client moved the cursor and pinched →
  **tile-1 counter incremented**; `fist_start` + wrist deltas →
  **WINDOW A dragged** to the viewport clamp; `fist_end` released
  (grabbing class dropped). Screenshot inspected.
- controller page loads and the vendored `vision_bundle.mjs` imports
  (status reaches "idle — tap Start camera"); camera path itself needs a
  real device — untestable headless.
- `caddy validate` on the synced Caddyfile: **valid**.
- live tony-ha: chaba-home views now `ai / chat / gesture / report /
  nobito`.

## NOT done — post-merge deploy steps (need tony-dell)

1. Merge this branch → `master` on the `chaba-tony-dell` checkout.
2. `podman build -t localhost/gesture-relay:latest stacks/tony-dell/gesture-relay`
   then `bash stacks/tony-dell/gesture-relay/install.sh` (renders the
   tailnet PublishPort, daemon-reload, starts `gesture-relay.service`).
3. Reload the web stack Caddy (`docker compose -f stacks/web/docker-compose.yml restart web`
   or `caddy reload`) so the new routes + `public/apps/gesture/` go live.
4. Then the card's expected_goals should pass:
   `/apps/gesture/` 200, `/apps/gesture/screen` 200,
   `/apps/gesture-live/health` 200, ws handshake on
   `/apps/gesture-live/ws`.
5. Real-hardware E2E: screen page on the TV browser, controller on the
   iPhone Safari tab. iOS caveat: getUserMedia needs HTTPS (tailnet URL
   is fine) and is unreliable inside an installed PWA — use a plain
   Safari tab.

## Notes / caveats

- The relay is unauthenticated by design — tailnet-only bind + Caddy edge
  is the boundary. Do not expose it on LAN or the public edge.
- "Cast to TV" currently casts the yolo service's annotated `/image`
  frame (what `/apps/yolo/api/cast` does server-side). Casting the
  gesture screen itself to a Chromecast would need a yolo `/cast`
  extension or an HA token on the client — flagged in the jobs doc.
- Port 8794 chosen (8787/8789/8790/8792 already in the registry).
