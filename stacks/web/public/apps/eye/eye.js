/* eye.js — Chaba Nest edge vision.
 *
 * Sources:
 *   ?src=me            device camera via getUserMedia (default)
 *   ?src=cam:<name>    cameras.json HLS stream (hls.js / native on iOS)
 *   ?src=snap:<name>   Frigate latest.jpg refresh (weakest devices)
 *
 * Detection: MediaPipe tasks-vision ObjectDetector, efficientdet-lite0
 * int8 (~4.4MB), VIDEO mode, drawn on an overlay canvas. Runs entirely
 * in-browser — the Nest's edge tier; server only serves static files.
 *
 * Bench: ?bench=N runs N detections, reports fps + inference ms
 * (p50/p95), model, and device UA in-page; attempts to POST the row to
 * MDDB (bench/edge-*) so device capability is measured, not guessed.
 */
import { FilesetResolver, ObjectDetector } from '../vendor/mediapipe/vision_bundle.mjs';

const params = new URLSearchParams(location.search);
const src = params.get('src') || 'me';
const benchN = parseInt(params.get('bench') || '0', 10);
const MODEL = 'efficientdet_lite0_int8';
const MDDB = 'https://idc03.taila0626a.ts.net/mddb/v1';

const vid = document.getElementById('vid');
const overlay = document.getElementById('overlay');
const ctx = overlay.getContext('2d');
const statEl = document.getElementById('stat');
const srcEl = document.getElementById('src');
const benchEl = document.getElementById('bench');

let detector = null;
let bench = null;

async function loadDetector() {
  const t0 = performance.now();
  const vision = await FilesetResolver.forVisionTasks('/apps/vendor/mediapipe/');
  detector = await ObjectDetector.createFromOptions(vision, {
    baseOptions: { modelAssetPath: '/apps/eye/model.tflite' },
    scoreThreshold: 0.35,
    runningMode: 'VIDEO',
    maxResults: 12,
  });
  return Math.round(performance.now() - t0);
}

async function startStream() {
  if (src === 'me') {
    const stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: 'environment' }, audio: false });
    vid.srcObject = stream;
    srcEl.textContent = 'source: device camera';
  } else if (src.startsWith('cam:')) {
    const name = src.slice(4);
    const data = await (await fetch('/cameras.json')).json();
    const cam = (data.cameras || []).find(c => c.name === name);
    if (!cam) throw new Error(`cam not in cameras.json: ${name}`);
    if (!cam.hls_url) throw new Error(`cam ${name} has no hls_url — use snap:${name}`);
    // Chromium reports "maybe" for HLS but can't demux it — try hls.js
    // first, fall back to native (iOS Safari, which plays it natively).
    // NOTE: public traffic cams are CORS-blocked — hls.js fetch fails on
    // desktop; those streams only work via the native (iOS) path.
    await new Promise((res, rej) => {
      const s = document.createElement('script');
      s.src = '/apps/vcast/hls.min.js';
      s.onload = res; s.onerror = () => rej(new Error('hls.js load failed'));
      document.head.appendChild(s);
    });
    if (window.Hls?.isSupported()) {
      const hls = new window.Hls({ lowLatencyMode: true });
      hls.on(window.Hls.Events.ERROR, (_, d) => {
        if (d.fatal) throw new Error(`hls: ${d.details}`);
      });
      hls.loadSource(cam.hls_url);
      hls.attachMedia(vid);
    } else {
      vid.src = cam.hls_url;
    }
    await vid.play();
    srcEl.textContent = `source: cam:${name}`;
  } else if (src === 'test') {
    // Synthetic animated frames — verifies detector + measures real
    // inference latency without a camera/stream. Bench-safe source.
    srcEl.textContent = 'source: test (synthetic)';
    return '__test__';
  } else if (src.startsWith('snap:')) {
    const name = src.slice(5);
    // Snapshot refresh -> draw frames onto a synthetic video-like path:
    // reuse an <img> polled every 2s, detect on the drawn image.
    srcEl.textContent = `source: snap:${name} (2s poll)`;
    return name;
  }
  return null;
}

let snapImg = null;
let testCanvas = null;
async function snapFrame(name) {
  if (name === '__test__') {
    if (!testCanvas) {
      testCanvas = document.createElement('canvas');
      testCanvas.width = 640; testCanvas.height = 480;
      testCanvas.style.cssText =
        'position:absolute;inset:0;width:100%;height:100%;object-fit:contain;';
      document.getElementById('stage').insertBefore(testCanvas, overlay);
    }
    const c = testCanvas.getContext('2d');
    c.fillStyle = '#1a2030'; c.fillRect(0, 0, 640, 480);
    const t = Date.now() / 1000;
    for (let i = 0; i < 12; i++) {
      c.fillStyle = `hsl(${(i * 31 + t * 40) % 360} 70% 55%)`;
      c.fillRect((Math.sin(t + i) * 0.5 + 0.5) * 560 + 20,
                 (Math.cos(t * 0.7 + i * 2) * 0.5 + 0.5) * 400 + 20,
                 60, 60);
    }
    c.fillStyle = '#fff'; c.font = '20px monospace';
    c.fillText(new Date().toISOString(), 12, 462);
    return testCanvas;
  }
  if (!snapImg) {
    snapImg = new Image();
    snapImg.crossOrigin = 'anonymous';
  }
  await new Promise((res) => {
    snapImg.onload = res; snapImg.onerror = res;
    snapImg.src = `/frigate/api/${name}/latest.jpg?t=${Date.now()}`;
  });
  return snapImg;
}

function draw(dets) {
  const w = vid.videoWidth || snapImg?.naturalWidth || testCanvas?.width || 0;
  const h = vid.videoHeight || snapImg?.naturalHeight || testCanvas?.height || 0;
  if (!w || !h) return;
  overlay.width = w; overlay.height = h;
  ctx.clearRect(0, 0, w, h);
  ctx.font = `${Math.max(14, w / 60)}px monospace`;
  ctx.lineWidth = Math.max(2, w / 400);
  for (const d of dets) {
    const bb = d.boundingBox;
    if (!bb) continue;
    const label = d.categories?.[0];
    ctx.strokeStyle = '#4cd2ff';
    ctx.strokeRect(bb.originX, bb.originY, bb.width, bb.height);
    const tag = `${label?.categoryName ?? '?'} ${(label?.score ?? 0).toFixed(2)}`;
    const tw = ctx.measureText(tag).width;
    ctx.fillStyle = '#4cd2ff';
    ctx.fillRect(bb.originX, bb.originY - 24, tw + 10, 24);
    ctx.fillStyle = '#000';
    ctx.fillText(tag, bb.originX + 5, bb.originY - 6);
  }
}

function pct(a, p) {
  if (!a.length) return 0;
  const s = [...a].sort((x, y) => x - y);
  return s[Math.min(s.length - 1, Math.floor(p * s.length))];
}

async function finishBench(samples, modelLoadMs) {
  const p50 = pct(samples, 0.5), p95 = pct(samples, 0.95);
  const fps = (1000 / (p50 || 1)).toFixed(1);
  const row = {
    model: MODEL, n: samples.length,
    infer_ms_p50: p50, infer_ms_p95: p95, fps: +fps,
    load_ms: modelLoadMs,
    ua: navigator.userAgent.slice(0, 160),
    w: vid.videoWidth || 0, h: vid.videoHeight || 0,
    ts: new Date().toISOString(),
  };
  const txt = `bench done — ${MODEL}\n${samples.length} frames  ${fps} fps\ninfer p50 ${p50.toFixed(0)}ms  p95 ${p95.toFixed(0)}ms\nload ${modelLoadMs}ms`;
  benchEl.textContent = txt;
  statEl.textContent = txt.split('\n')[1];
  // Best-effort record — MDDB CORS may refuse; keep it non-fatal.
  try {
    await fetch(`${MDDB}/add`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        collection: 'ada-ha-scenario-reports',
        key: `bench/edge-${Date.now()}`,
        contentMd: '```json\n' + JSON.stringify(row, null, 2) + '\n```',
        meta: { kind: ['report'], domain: ['bench'], attribute: ['bench'],
                title: [`edge bench ${MODEL}`], updated: [row.ts],
                lang: ['en'], written_by: ['eye-page'] },
      }),
    });
  } catch (_) { /* offline/closed-origin: the on-page panel still shows */ }
}

async function loop(snapName, modelLoadMs) {
  const samples = [];
  const tick = async () => {
    const srcEl2 = snapName ? await snapFrame(snapName) : vid;
    const ready = snapName === '__test__' ? true
                : snapName ? (snapImg?.naturalWidth > 0)
                : (vid.readyState >= 2 && vid.videoWidth > 0);
    if (ready) {
      const t0 = performance.now();
      // VIDEO-mode API accepts any ImageSource (video/img/canvas).
      const res = detector.detectForVideo(srcEl2, t0);
      const ms = performance.now() - t0;
      draw(res.detections || []);
      if (bench) {
        samples.push(ms);
        if (samples.length <= benchN) {
          benchEl.textContent =
            `bench ${samples.length}/${benchN}  last ${ms.toFixed(0)}ms`;
          if (samples.length === benchN) { bench = false; await finishBench(samples, modelLoadMs); }
        }
      } else {
        statEl.textContent = `${(res.detections || []).length} obj · ${ms.toFixed(0)}ms`;
      }
    }
    setTimeout(tick, snapName ? 2000 : 0);   // rAF-ish; snap polls slower
  };
  tick();
}

(async () => {
  try {
    const loadMs = await loadDetector();
    const snapName = await startStream();
    statEl.textContent = `detector ready (${loadMs}ms)`;
    if (benchN > 0) { bench = true; benchEl.classList.add('show'); }
    await loop(snapName, loadMs);
  } catch (e) {
    statEl.textContent = `error: ${e.message}`;
  }
})();
