---
title: Gesture UI — ada_v2 flow and YOLO assessment
description: How the ada_v2 "Minority Report" hand-gesture UI worked end to end, whether the same could be built with YOLO, and recommendations for reviving gesture control in ada-pi
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
  ]
---

# Gesture UI — ada_v2 flow and YOLO assessment

## What it is

Assessment of the retired ada_v2 "Minority Report" gesture interface
(source: archived repo `tonezzz/ada` @ `af6d572`, `ada_v2/src/App.jsx`)
and whether YOLO could replace MediaPipe as the recognition engine.

## ada_v2 gesture flow (as shipped)

All client-side in the React/Electron frontend; the Python backend never
saw gesture data — only downscaled frames for Gemini vision, a separate
path.

1. **Model init** — fetch `/hand_landmarker.task` (7.8 MB MediaPipe
   HandLandmarker from `public/`); WASM runtime via
   `FilesetResolver.forVisionTasks` (jsdelivr CDN);
   `HandLandmarker.createFromOptions({delegate: "GPU",
   runningMode: "VIDEO", numHands: 1})`.
2. **Capture** — `getUserMedia` at 1920×1080 → `<video>` →
   `requestAnimationFrame(predictWebcam)` loop (~60 fps, GPU inference).
3. **Per frame** — `detectForVideo()` → 21 normalized landmarks, then:

   - **Cursor**: index fingertip (landmark 8) → sensitivity scaling
     (center 50 % of camera maps to 100 % of screen) → clamp → lerp
     smoothing (α = 0.2) → snap-to-button with hysteresis (snap 50 px,
     unsnap 100 px; scans `button, input, select, .draggable`, adds cyan
     glow) → virtual cursor.
   - **Pinch = click**: `dist(lm4, lm8) < 0.05` (normalized) → rising
     edge → `document.elementFromPoint()` → `.closest('button, input,
     a, [role=button]')` → `.click()`.
   - **Fist = grab/drag**: all 4 fingers folded (tip closer to wrist
     than its MCP) → hit-test cursor vs. popup rects (cad, browser,
     kasa, printer) → bringToFront → drag by **wrist** deltas (lm0 —
     the wrist doesn't move when forming a fist). Any non-fist
     releases — the README's "open palm = release" is just the natural
     non-fist pose.
   - Debug: cyan skeleton overlay on the video canvas.

`ada_v2/hand_gesture_test.py` was a standalone OpenCV prototype with a
wider vocabulary (point directions, peace sign) — scratch code, not the
shipped path.

## Can YOLO do it?

Not directly — wrong-shaped output. YOLO detection gives bounding boxes
+ class labels; the ada_v2 UX needs continuous 21-point landmark
geometry (fingertip pointer, sub-pixel pinch distance).

| Requirement | YOLO detection | YOLO-pose (keypoints) |
|---|---|---|
| Fingertip cursor (sub-pixel) | box centre only — too coarse | yes, if trained on hand-keypoint data |
| Pinch distance | not possible | yes |
| Fist/palm classification | yes (train classes, e.g. HaGRID) | derived from keypoints |

### Pros

- **Range/scale** — MediaPipe's palm detector drops hands beyond ~1–2 m;
  a YOLO trained on diverse data detects raised hands across a room
  (kiosk / wall tablet / TV surfaces).
- **Multi-hand/multi-person** tracking is more robust at distance.
- **Vocabulary growth** — new poses = retrain, no hand-tuned landmark
  heuristics (ada_v2's folded-finger check is brittle: ignores thumb,
  2-D only).
- Easy server-side GPU inference via ultralytics.

### Cons

- Boxes ≠ landmarks — gesture-class YOLO loses the pointer UX that made
  it feel like Minority Report.
- Custom data/training burden beyond HaGRID's vocabulary.
- Latency — browser WASM/WebGPU MediaPipe runs ~60 fps locally; a server
  round-trip adds 30–100 ms, felt immediately in a pointer UI.
- In-browser YOLO (TFJS/ONNX.js) is heavier than MediaPipe WASM.
- On Pi-class hardware (ada-pi): YOLO won't hit interactive rates on
  CPU; MediaPipe TFLite gets ~15–30 fps on Pi 5, or needs the Hailo AI
  HAT.

## Recommendation

1. **Keep MediaPipe** if reviving for ada-pi/PWA — or bump to
   `tasks-vision` WebGPU delegate, or `GestureRecognizer` (prebuilt
   classes: closed fist, open palm, point-up, thumbs up/down, victory).
   The feature was dropped for product reasons, not because it failed.
2. **Use YOLO where it wins** — a "hand raised" wake/attention gesture
   for room-scale surfaces. Hybrid: cheap YOLO watch → activate the
   landmark pipeline only while a hand is up.
3. **Keep the UX layer** — lerp smoothing, snap-with-hysteresis,
   wrist-delta dragging are model-agnostic and made it usable. With
   YOLO classes add N-of-M temporal voting to stop label flicker.
4. **Pi hardware** — prefer inference in the PWA (browser already has
   webcam + GPU) over streaming frames to a GPU server; privacy and
   latency both better.

Net: YOLO can do gesture *recognition*; ada_v2 was a landmark-driven
*pointer system*. For that, MediaPipe (or any 21-keypoint model) is the
right primitive. YOLO is the answer only if the goal shifts to
room-scale, discrete, multi-person gestures.

## References

- Archive report: `docs/kb/archive/ada/ada-v2-platform.md`
- Manifest: `docs/archive/manifests/ada.yml`
- Source: `tonezzz/ada` @ `af6d572` — `ada_v2/src/App.jsx` (lines
  ~1069–1548), `ada_v2/hand_gesture_test.py`, `ada_v2/README.md`
