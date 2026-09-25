---
title: Gesture UI — ada_v2 complete implementation reference + YOLO assessment
description: Full rebuild reference for the ada_v2 "Minority Report" hand-gesture UI — every constant, state machine, DOM contract, and edge case extracted from the archived source — plus the YOLO feasibility assessment and revival checklist
tags: [gesture, mediapipe, yolo, ada_v2, ada-pi, computer-vision, hand-tracking]
created: 2026-09-25
updated: 2026-09-25
category: architecture
related: [docs/kb/archive/ada/ada-v2-platform.md, docs/archive/manifests/ada.yml]
search_keywords:
  [
    hand gesture control,
    mediapipe hand landmarker,
    pinch click fist drag,
    minority report ui,
    yolo gesture recognition,
    ada_v2 gesture,
    hand tracking ada-pi,
    rebuild gesture ui,
    hand landmarker task file,
  ]
---

# Gesture UI — ada_v2 complete implementation reference + YOLO assessment

Self-contained reference for rebuilding the ada_v2 hand-gesture UI. Everything
needed is in this file — no re-digging the archive required.

**Source of truth:** `tonezzz/ada` (archived) @ `af6d57223f72fce68b4d6f47bbfc6a75b7bc0085`
— `ada_v2/src/App.jsx` (gesture pipeline lines ~1068–1558, window manager
~339–413, ~510–536, ~1720–1876, render ~1919–2238), `ada_v2/package.json`,
`ada_v2/electron/main.js`, `ada_v2/src/index.css`,
`ada_v2/src/components/ToolsModule.jsx`, `ada_v2/backend/server.py`,
`ada_v2/hand_gesture_test.py`, `ada_v2/README.md`.

## Architecture at a glance

```
Webcam (getUserMedia 1920x1080)
  -> <video> (hidden, opacity-0)
  -> requestAnimationFrame(predictWebcam)        ~60fps when video on
       |- drawImage -> visible <canvas>          (CAM_01 tile, optional mirror)
       |- every 5th frame -> 640x360 canvas -> JPEG q0.6
       |     -> socket.emit('video_frame')       -> backend ada.py
       |     -> audio_loop.send_frame -> Gemini Live vision  (side-channel)
       '- if handTracking enabled && new video frame:
             detectForVideo -> 21 normalized landmarks
             -> fingertip cursor math -> pinch click / fist drag
             -> cyan skeleton drawn on canvas
```

All gesture interpretation is **browser-local**. The backend never saw gesture
events — the two paths (UI control vs AI vision) are fully independent.

## Dependencies & assets

- `@mediapipe/tasks-vision` `^0.10.22-rc.20250304` (npm dep in package.json)
- WASM runtime loaded from CDN: `FilesetResolver.forVisionTasks(
  "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.0/wasm")` —
  **note the version skew** (CDN pinned @0.10.0 vs npm rc-20250304)
- Model: `/hand_landmarker.task` served from `public/` (~7.8 MB, Google's stock
  HandLandmarker full model)
- React 18, socket.io-client 4.7.4, electron 28, vite 5, lucide-react icons
- Electron: frameless 1920x1080 window (`frame: false`); top bar uses
  `WebkitAppRegion: 'drag'` (mouse-only OS window drag)

## Init sequence (runs once, guarded)

```js
const vision = await FilesetResolver.forVisionTasks(
    "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.0/wasm");
handLandmarkerRef.current = await HandLandmarker.createFromOptions(vision, {
    baseOptions: { modelAssetPath: "/hand_landmarker.task", delegate: "GPU" },
    runningMode: "VIDEO",
    numHands: 1
});
```

- First `fetch('/hand_landmarker.task')` verifies the file exists (logs
  content-type/length) before creating the landmarker.
- Guarded by `handLandmarkerInitStartedRef` — init runs once on mount.
- Success posts "Hand Tracking Ready" to the chat; failure posts the error.

## Capture & loop

- `getUserMedia({ video: { width: ideal 1920, height: ideal 1080,
  aspectRatio: 16/9, deviceId? } })` -> `video.srcObject` -> `play()`.
- `predictWebcam` runs via `requestAnimationFrame` only while `isVideoOn`.
- Guards: bail if `video.readyState < 2` or `videoWidth/Height === 0`
  (prevents MediaPipe crash on cold start).
- Dedup: `video.currentTime !== lastVideoTimeRef` — skips inference on
  repeated frames.
- `detectForVideo(video, performance.now())` — needs monotonic ms timestamp.
- Hand tracking requires **video ON** (`isVideoOn`) **and** the Hand toggle
  (`isHandTrackingEnabled`, default OFF) — two separate switches.
- FPS counter displayed in top bar while video is on.

## Constants (verified from source)

| Constant | Value | Location |
|---|---|---|
| SENSITIVITY | `cursorSensitivity`, default **2.0** | settings slider; center 50% of camera maps to 100% of screen |
| LERP | **0.2** | `smoothedCursorPos += (target - smoothed) * 0.2` |
| SNAP_THRESHOLD | **50 px** | snap cursor to closest interactive element's center |
| UNSNAP_THRESHOLD | **100 px** | hysteresis — must pass 100px to release |
| PINCH threshold | **0.05** | normalized `dist(lm4, lm8)` |
| Drag deadzone | **0.5 px** | ignore wrist deltas below this |
| Transmission | **640x360, JPEG q0.6, every 5th frame** | `video_frame` socket event |
| numHands | **1** | second hand ignored |
| z base | **30** | `getZIndex = 30 + index in zIndexOrder` |

## Cursor math (per detected frame)

```js
rawX   = isCameraFlipped ? 1 - lm8.x : lm8.x;   // optional mirror
normX  = clamp((rawX - 0.5) * SENSITIVITY + 0.5, 0, 1);
normY  = clamp((lm8.y - 0.5) * SENSITIVITY + 0.5, 0, 1);   // y not flipped
target = normX * innerWidth, normY * innerHeight;
smoothed += (target - smoothed) * 0.2;          // lerp
finalX/finalY = smoothed (unless snapped);
```

**Snap hysteresis** — every frame scans
`document.querySelectorAll('button, input, select, .draggable')`, finds the
element whose **rect center** is nearest the cursor; if `dist < 50px` the
cursor locks to that center and the element gets a cyan glow
(`boxShadow 0 0 20px rgba(34,211,238,.6)`, `backgroundColor rgba(6,182,212,.2)`,
`borderColor cyan` — all **inline styles**; `.snap-highlight` class is added
but has no CSS). Releases only when cursor drifts `> 100px` from the snap
point.

## Pinch = click

- `dist(lm4, lm8) < 0.05` in normalized coordinates.
- **Rising edge only**: fires when `isPinchNow && !isPinching` — one click per
  pinch, hold doesn't repeat.
- Hit-test: `document.elementFromPoint(finalX, finalY)` then
  `el.closest('button, input, a, [role="button"]')` -> `.click()`; falls back
  to `el.click()` if no clickable ancestor.
- Consequence: pinch fires `.click()` but **not** mousedown/mouseup — elements
  driven by pointer-down handlers (drag handles, 3D canvas) don't respond to
  pinch. Dragging is fist-only.

## Fist = grab/drag window

```js
isFingerFolded(tip, mcp) = dist(tip, lm0_wrist) < dist(mcp, lm0_wrist)
isFist = folded(8,5) && folded(12,9) && folded(16,13) && folded(20,17)
         // index, middle, ring, pinky — thumb NOT checked
```

- On fist, if no drag active: hit-test cursor against `getBoundingClientRect()`
  of **`['cad','browser','kasa','printer']`** (popup window ids only) — cursor
  inside rect -> `activeDragElement = id`, `bringToFront(id)`, lock wrist pos.
- While fist held: compute **wrist (lm0)** screen pos with the same
  flip/sensitivity/clamp math (no lerp), delta vs last wrist pos; apply via
  `updateElementPosition(id, dx, dy)` when `|dx|>0.5 || |dy|>0.5`.
- Wrist (not fingertip) is used because the wrist doesn't move while forming
  the fist — fingertip would jump.
- Any non-fist frame releases (`activeDragElement = null`). The README's
  "open palm = release" is just the natural non-fist pose.
- `activeDragElement` also drives a green ring highlight on the grabbed window.

## Window manager contract (what gestures manipulate)

- `elementPositions` / `elementSizes` maps; **anchors differ per element**:
  - `chat`: top-center (`translate(-50%,0)`) — x=中心, y=top edge
  - `video`: top-left
  - everything else: center (`translate(-50%,-50%)`)
- `updateElementPosition` clamps to viewport bounds per anchor type
  (margin 0); `clampToViewport` (margin 10, topBar 60) is used for popup
  initial placement.
- `zIndexOrder` array; `getZIndex = 30 + index`; `bringToFront` moves id to
  end of array.
- `fixedElements = ['visualizer','chat','video','tools']` — never mouse-draggable.
- Mouse path: `handleMouseDown` requires `[data-drag-handle]` inside the
  target **unless** modular mode is on; blocks drag start on
  input/button/textarea/canvas. Fist-drag bypasses the handle requirement and
  works anywhere inside the four popup rects.
- Popup visibility toggles (`showCadWindow` etc.) come from socket events
  (`cad_data`, `browser_frame`, `request_print_window`) or ToolsModule buttons.

## DOM contract for a rebuild

- Hidden `<video>` (opacity-0) + visible `<canvas>` (80% opacity, optional
  `scaleX(-1)` mirror) inside a `w-80 aspect-video` tile labeled CAM_01,
  fixed bottom-right, id=`video`, z=20.
- Cursor: `fixed w-6 h-6 border-2 rounded-full pointer-events-none z-[100]`
  cyan ring + white center dot at `{left: cursorPos.x, top: cursorPos.y,
  transform: translate(-50%,-50%)}`; while pinching it gets
  `bg-cyan-400 scale-75` + stronger glow.
- Popup windows: `id={cad|browser|kasa|printer}`, positioned `absolute` at
  `elementPositions[id]` with `translate(-50%,-50%)`, `zIndex: getZIndex(id)`,
  `data-drag-handle` on their header bars for mouse drag.
- Hand toggle: `Hand` icon button in bottom `ToolsModule` toolbar — orange
  border/glow when enabled.
- Settings: `SettingsWindow` exposes `cursorSensitivity` slider +
  `isCameraFlipped` checkbox; **flip is persisted server-side** —
  backend `settings.json` key `camera_flipped`, pushed on `settings` socket
  event, applied via `setIsCameraFlipped`. (Sensitivity stays client-side.)

## Debug/visual aids

- `drawSkeleton`: cyan `HAND_CONNECTIONS` lines on the display canvas at
  native resolution.
- Logging: "Tracking loop running... Hand Found/No Hand" every 100 frames;
  "First hand detection!" once.
- Removed features still referenced: `cursorTrailRef`, `ripples` state,
  "Trail Logic"/"Ripple Effect" comments — dead code, don't port.

## Worked trace with real values

Cursor — index tip `lm8=(0.58, 0.30)`, screen 1920x1080, SENSITIVITY=2.0:

```
norm    = ((0.58-.5)*2+.5, (0.30-.5)*2+.5)  =  (0.66, 0.10)
target  = (1267, 108) px
lerp a=0.2:  f1 (253,22) -> f3 (618,53) -> f6 (935,80) -> ... -> (1267,108)
```

Snap — button center at (1264,198): dist 16px < 50 -> snaps & locks; drift
60px -> still glued (<=100); drift 120px -> unsnaps.

Pinch — `dist(lm4,lm8) = 0.0071 < 0.05` -> rising edge -> elementFromPoint ->
`.closest('button…').click()`.

Fist drag — all four tips closer to wrist than their MCPs -> cursor inside
`cad` rect -> grab; wrist `(0.55,0.62)->(0.58,0.60)` -> screen
`(1152,799)->(1267,756)` -> `updateElementPosition('cad', +115, -43)`.

## Edge cases & sharp edges

- `numHands: 1` — a second hand is silently ignored; `landmarks[0]` wins.
- Smoothed cursor starts at (0,0) — first frames lerp in from the corner;
  `lastWristPos` only locks on grab so drag doesn't jump.
- Snap scan is O(all interactive DOM nodes) every frame — fine at this scale,
  cache the list if porting to a bigger DOM.
- Fist hit-test uses the *smoothed/snapped* cursor position (finalX/finalY),
  not the wrist — so you aim with the fingertip, then clench.
- Thumb isn't part of the fist check — thumb-out fist still counts (and is
  required for the pinch detector to not conflict).
- `elementFromPoint` ignores `pointer-events-none` layers (cursor, noise,
  backdrop) — by design they can't be clicked or hit-tested.
- No scroll gesture, no right-click, no two-hand gestures, no dwell click.
- Browser/Safari: MediaPipe WASM works but needs a secure context and a user
  gesture for camera permission; iOS standalone-PWA mic issues are
  audio-specific but camera in PWA mode is its own gamble — test early.
- CDN WASM pin (@0.10.0) vs npm dep (0.10.22-rc) mismatch — vendor both for
  a rebuild (same pattern as vendored echarts `/local/` assets on HA hosts).

## Can YOLO do it?

Not directly — wrong-shaped output. YOLO detection gives bounding boxes +
class labels; the ada_v2 UX needs continuous 21-point landmark geometry
(fingertip pointer, sub-pixel pinch distance).

| Requirement | YOLO detection | YOLO-pose (keypoints) |
|---|---|---|
| Fingertip cursor (sub-pixel) | box centre only — too coarse | yes, if trained on hand-keypoint data |
| Pinch distance | not possible | yes |
| Fist/palm classification | yes (train classes, e.g. HaGRID) | derived from keypoints |

### Pros

- **Range/scale** — MediaPipe's palm detector drops hands beyond ~1-2 m; a
  YOLO trained on diverse data detects raised hands across a room (kiosk /
  wall tablet / TV surfaces).
- **Multi-hand/multi-person** tracking is more robust at distance.
- **Vocabulary growth** — new poses = retrain, no hand-tuned landmark
  heuristics (ada_v2's folded-finger check is brittle: ignores thumb, 2-D only).
- Easy server-side GPU inference via ultralytics.

### Cons

- Boxes != landmarks — gesture-class YOLO loses the pointer UX that made it
  feel like Minority Report.
- Custom data/training burden beyond HaGRID's vocabulary.
- Latency — browser WASM/WebGPU MediaPipe runs ~60 fps locally; a server
  round-trip adds 30-100 ms, felt immediately in a pointer UI.
- In-browser YOLO (TFJS/ONNX.js) is heavier than MediaPipe WASM.
- On Pi-class hardware (ada-pi): YOLO won't hit interactive rates on CPU;
  MediaPipe TFLite gets ~15-30 fps on Pi 5, or needs the Hailo AI HAT.

## Recommendation

1. **Keep MediaPipe** if reviving for ada-pi/PWA — or bump to `tasks-vision`
   WebGPU delegate, or `GestureRecognizer` (prebuilt classes: closed fist,
   open palm, point-up, thumbs up/down, victory). The feature was dropped for
   product reasons, not because it failed.
2. **Use YOLO where it wins** — a "hand raised" wake/attention gesture for
   room-scale surfaces. Hybrid: cheap YOLO watch -> activate the landmark
   pipeline only while a hand is up.
3. **Keep the UX layer** — lerp smoothing, snap-with-hysteresis, wrist-delta
   dragging are model-agnostic and made it usable. With YOLO classes add
   N-of-M temporal voting to stop label flicker.
4. **Pi hardware** — prefer inference in the PWA (browser already has webcam +
   GPU) over streaming frames to a GPU server; privacy and latency both better.

Net: YOLO can do gesture *recognition*; ada_v2 was a landmark-driven
*pointer system*. For that, MediaPipe (or any 21-keypoint model) is the
right primitive. YOLO is the answer only if the goal shifts to room-scale,
discrete, multi-person gestures.

## Rebuild checklist (ada-pi / PWA)

1. Vendor `hand_landmarker.task` + tasks-vision WASM locally (no CDN
   dependency; version-lock both to the same release).
2. Port `predictWebcam` verbatim: readyState guard -> canvas draw ->
   (optional) backend frame relay -> landmark pipeline.
3. Port cursor pipeline: flip -> sensitivity -> clamp -> lerp -> snap
   hysteresis -> setCursorPos; DOM cursor div; pinch/fist state machines;
   wrist-delta drag + bounds-by-anchor.
4. Recreate the DOM contract: popup ids, `data-drag-handle`, snap target
   selector, cursor div, Hand toggle button, settings (sensitivity + flip).
5. Decide persistence: ada_v2 kept `camera_flipped` in backend settings.json —
   in ada-pi pick the equivalent (HA input_boolean / PWA localStorage /
   backend settings file).
6. Improve on it: add dwell-click or N-of-M pinch voting, second-hand support
   (`numHands: 2`), `GestureRecognizer` for extra vocabulary, wake-word-style
   "hand up" gate to save GPU when idle.

## References

- Archive report: `docs/kb/archive/ada/ada-v2-platform.md`
- Manifest: `docs/archive/manifests/ada.yml`
- Source: `tonezzz/ada` @ `af6d572` — `ada_v2/src/App.jsx`,
  `ada_v2/src/components/{ToolsModule,SettingsWindow,...}.jsx`,
  `ada_v2/backend/server.py`, `ada_v2/electron/main.js`,
  `ada_v2/hand_gesture_test.py` (standalone OpenCV prototype — wider vocab
  incl. directional pointing + peace sign; scratch code, not shipped),
  `ada_v2/README.md`, `ada_v2/package.json`
