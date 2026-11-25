# Dispatch outcome — explore-yolo-for-gesture-control-in-apps-8e27eb (attempt 2)

## What changed

Working prototype integrated into `/apps/eye/` (commit `c2a9396` on
`dispatch/20261125-201656-evaluate-replacing-mediapipe-w`, NOT pushed):

- `stacks/web/public/apps/eye/eye-yolo.js` (new) — ONNX Runtime Web
  detector factory; letterbox 640 preprocess, JS NMS, mirrors the
  MediaPipe `detectForVideo` slice `eye.js` uses.
- `stacks/web/public/apps/eye/eye.js` — new `?det=yolo` param (default
  `mediapipe` unchanged); awaits the now-async detect call; bench/publish
  model string gains `-<variant>/<ep>`.
- `stacks/web/public/apps/eye/model-yolo.onnx` (new, 9.8MB FP32) —
  YOLO26n exported locally from `SuperSura/hand-gesture-yolo26n` .pt
  (Apache-2.0, HaGRID 12 gesture classes) via ultralytics 8.4.218,
  opset 12, imgsz 640.
- `stacks/web/public/apps/vendor/onnxruntime-web/` (new, ~70MB) —
  onnxruntime-web@1.31.1 bundle + the wasm binaries it actually fetches
  (`asyncify` for WASM EP, `jsep` for WebGPU EP).
- `?src=img:<path>` source added for camera-free bench/det checks;
  `eye/test/hagrid-*.jpg` = 4 HaGRID sample images.
- `docs/ssot/jobs/eye/2026-11-25-yolo-onnx-gesture-eval.yml` — full eval;
  `docs/runbooks/eye-cast.md` updated.

## Result / verification

Verified in headless Chrome (puppeteer-core, real wall-clock) against a
local static server:

- Detection: HaGRID "call" images → `call 0.88–0.90`, single box —
  end-to-end gesture detection works.
- Bench, CPU WASM EP (i7-6700HQ, single-thread — no COOP/COEP):
  YOLO26n-fp32 p50 ~410–419ms, p95 ~632ms, ~2.4fps, load ~1.3s
  vs MediaPipe efficientdet-lite0-int8 p50 ~103–116ms, p95 ~247–262ms,
  ~9fps, load ~280ms → **MediaPipe ~4x faster on CPU**.
- WebGPU EP: session+run verified functional via SwiftShader flags
  (15s/frame is software-rendering noise; needs a real-GPU bench).
- Dynamic-INT8 ONNX variant tried and rejected: ORT-web WASM runs
  DynamicQuantizeLinear per activation → p50 2665ms (~6.5x slower).
- The obvious HF ONNX (Neural-Hacker/hand_gesture_yolo) is broken for
  all ORT consumers (fp16 into DynamicQuantizeLinear) — documented.

Verdict: prototype meets the done-condition; on CPU it is NOT a
MediaPipe replacement. Its value is 12 hand-gesture classes (vs COCO
objects) and the WebGPU path — cutover decision needs a real-GPU bench
on tony-dell/omen. Default stays `det=mediapipe`.

## How to verify

```
cd stacks/web/public && python3 -m http.server 8777
# then in a browser:
#   /apps/eye/?src=img:test/hagrid-call-0.jpg&det=yolo        (det check)
#   /apps/eye/?src=test&det=yolo&bench=60                     (bench)
#   /apps/eye/?src=test&bench=60                              (mediapipe baseline)
```

## lessons:

- onnxruntime-web@1.31 `ort.webgpu.bundle.min.mjs` fetches
  `ort-wasm-simd-threaded.asyncify.{mjs,wasm}` for its WASM EP — the
  plain `.wasm` is NOT what this bundle wants; missing files surface as
  "previous call to 'initWasm()' failed".
- `--virtual-time-budget` headless Chrome benches report ~0ms inference
  (virtual clock) — use puppeteer-core with real time for ORT/ML timings.
- ORT-web WASM `quantize_dynamic` INT8 is a pessimization (~6x slower
  than FP32): DynamicQuantizeLinear runs per activation; only static
  QDQ/ConvInteger quant helps on wasm.
- Check HF ONNX gesture models before vendoring: Neural-Hacker
  hand_gesture_yolo is fp16-QDQ-broken for every ORT consumer.
- YOLO26-family ONNX exports emit probabilities directly (no sigmoid)
  and cxcywh box coords already in input-pixel space.
