/* eye-yolo.js — YOLOv8n ONNX hand-gesture detector for /apps/eye.
 *
 * Selected by ?det=yolo (default stays 'mediapipe'). Runs fully in-browser
 * via onnxruntime-web: WebGPU EP when available, WASM EP fallback. No
 * external API — model + runtime are vendored static assets.
 *
 * Model: stacks/web/public/apps/eye/model-yolo.onnx
 *   YOLO26n FP32, 640x640 in, [1,16,8400] out (4 box + 12 gesture
 *   classes; class scores are already probabilities — do NOT sigmoid).
 *   Source: huggingface.co/SuperSura/hand-gesture-yolo26n (.pt,
 *   Apache-2.0, HaGRID 12-class subset, mAP50 0.994), exported to ONNX
 *   locally with ultralytics 8.4.218 / opset 12 / imgsz 640.
 *   (The obvious HF ONNX, Neural-Hacker/hand_gesture_yolo, is broken:
 *   its QDQ graph feeds float16 into DynamicQuantizeLinear and ORT
 *   rejects it — verified 2026-11-25.)
 *
 * The returned detector mirrors the slice of the MediaPipe ObjectDetector
 * API that eye.js uses: detectForVideo(src, t) ->
 *   { detections: [{ boundingBox:{originX,originY,width,height},
 *                    categories:[{categoryName,score}] }] }
 * boundingBox is in source-pixel coords (letterbox is undone), matching
 * what draw() expects.
 */
import * as ort from '/apps/vendor/onnxruntime-web/ort.webgpu.bundle.min.mjs';

// FP32 only. A dynamic-INT8 quantize_dynamic variant was tried and
// rejected: ORT-web WASM runs DynamicQuantizeLinear per activation and
// measured ~6x SLOWER than FP32 (p50 2665ms vs 410ms, 2026-11-25).
const MODEL_URL = '/apps/eye/model-yolo.onnx';
const INPUT = 640;
const CLASSES = ['like', 'palm', 'fist', 'peace', 'ok', 'one',
                 'three', 'four', 'call', 'point', 'grip', 'middle_finger'];
const SCORE_THR = 0.35;
const IOU_THR = 0.5;
const MAX_DET = 12;

let _canvas = null;
function letterboxCanvas() {
  if (!_canvas) {
    _canvas = document.createElement('canvas');
    _canvas.width = INPUT; _canvas.height = INPUT;
  }
  return _canvas;
}

function iou(a, b) {
  const x1 = Math.max(a.x1, b.x1), y1 = Math.max(a.y1, b.y1);
  const x2 = Math.min(a.x2, b.x2), y2 = Math.min(a.y2, b.y2);
  const inter = Math.max(0, x2 - x1) * Math.max(0, y2 - y1);
  const area = r => (r.x2 - r.x1) * (r.y2 - r.y1);
  return inter / (area(a) + area(b) - inter + 1e-9);
}

export async function createYoloDetector() {
  ort.env.wasm.wasmPaths = '/apps/vendor/onnxruntime-web/';
  ort.env.wasm.numThreads = Math.min(4, navigator.hardwareConcurrency || 4);

  const opts = { executionProviders: [], graphOptimizationLevel: 'all' };
  // Prefer WebGPU; verify with a real warmup run because EP support is
  // not guaranteed on every driver — fall back to WASM EP.
  let ep = 'wasm';
  if (navigator.gpu) {
    try {
      const s = await ort.InferenceSession.create(MODEL_URL,
        { ...opts, executionProviders: ['webgpu'] });
      await s.run({ images: new ort.Tensor('float32', new Float32Array(3 * INPUT * INPUT), [1, 3, INPUT, INPUT]) });
      ep = 'webgpu';
      return finish(s, ep, 'fp32');
    } catch (_) { /* fall through to wasm */ }
  }
  const s = await ort.InferenceSession.create(MODEL_URL,
    { ...opts, executionProviders: ['wasm'] });
  return finish(s, ep, 'fp32');

  function finish(session, epName, variant) {
    const inputName = session.inputNames[0];
    const outputName = session.outputNames[0];
    const cv = letterboxCanvas();
    const cctx = cv.getContext('2d', { willReadFrequently: true });
    const px = new Float32Array(3 * INPUT * INPUT);

    // returns {scale, ox, oy, sw, sh}: src -> 640 letterbox mapping
    function prep(src) {
      const sw = src.videoWidth || src.naturalWidth || src.width || 0;
      const sh = src.videoHeight || src.naturalHeight || src.height || 0;
      if (!sw || !sh) return null;
      const scale = Math.min(INPUT / sw, INPUT / sh);
      const dw = Math.round(sw * scale), dh = Math.round(sh * scale);
      const ox = Math.floor((INPUT - dw) / 2), oy = Math.floor((INPUT - dh) / 2);
      cctx.fillStyle = '#808080'; cctx.fillRect(0, 0, INPUT, INPUT);
      cctx.drawImage(src, ox, oy, dw, dh);
      const img = cctx.getImageData(0, 0, INPUT, INPUT).data;
      // NCHW, /255
      for (let y = 0; y < INPUT; y++) {
        for (let x = 0; x < INPUT; x++) {
          const si = (y * INPUT + x) * 4, di = y * INPUT + x;
          px[di] = img[si] / 255;
          px[INPUT * INPUT + di] = img[si + 1] / 255;
          px[2 * INPUT * INPUT + di] = img[si + 2] / 255;
        }
      }
      return { scale, ox, oy, sw, sh };
    }

    async function detectForVideo(src) {
      const m = prep(src);
      if (!m) return { detections: [] };
      const out = await session.run({
        [inputName]: new ort.Tensor('float32', px, [1, 3, INPUT, INPUT]),
      });
      const t = out[outputName]; // [1, 4+nc, 8400]
      const d = t.data, nc = t.dims[1] - 4, anchors = t.dims[2];
      const dets = [];
      for (let i = 0; i < anchors; i++) {
        let best = -1, bs = 0;
        for (let c = 0; c < nc; c++) {
          const v = d[(4 + c) * anchors + i]; // already a probability
          if (v > bs) { bs = v; best = c; }
        }
        if (bs < SCORE_THR) continue;
        const cx = d[i], cy = d[anchors + i];
        const w = d[2 * anchors + i], h = d[3 * anchors + i];
        // letterbox -> source pixels
        const x1 = (cx - w / 2 - m.ox) / m.scale;
        const y1 = (cy - h / 2 - m.oy) / m.scale;
        const x2 = (cx + w / 2 - m.ox) / m.scale;
        const y2 = (cy + h / 2 - m.oy) / m.scale;
        dets.push({
          x1: Math.max(0, x1), y1: Math.max(0, y1),
          x2: Math.min(m.sw, x2), y2: Math.min(m.sh, y2),
          cls: CLASSES[best], score: bs,
        });
      }
      // greedy NMS per class
      dets.sort((a, b) => b.score - a.score);
      const keep = [];
      for (const d of dets) {
        if (keep.filter(k => k.cls === d.cls).length >= MAX_DET) continue;
        if (keep.some(k => k.cls === d.cls && iou(k, d) > IOU_THR)) continue;
        keep.push(d);
        if (keep.length >= MAX_DET) break;
      }
      return {
        ep: epName,
        detections: keep.map(k => ({
          boundingBox: {
            originX: k.x1, originY: k.y1,
            width: k.x2 - k.x1, height: k.y2 - k.y1,
          },
          categories: [{ categoryName: k.cls, score: k.score }],
        })),
      };
    }
    return { detectForVideo, ep: epName, variant };
  }
}
