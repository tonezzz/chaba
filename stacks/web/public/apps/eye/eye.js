/* eye.js — Chaba Nest edge vision.
 *
 * Sources:
 *   ?src=me              device camera via getUserMedia (default)
 *   ?src=cam:<name>      cameras.json HLS stream (hls.js / native on iOS)
 *   ?src=snap:<name>     Frigate latest.jpg refresh (weakest devices)
 *   ?src=snap:<zone>/<key>  camwall last-good thumb — covers xmeye/DVR
 *                        channels (vms-noble-*) and all pulled zones
 *   ?src=vms:<channel>   fresh xmeye frame via /apps/vms-snap proxy
 *                        (mn01 shim ~10s/capture; serial polling)
 *   ?src=test            synthetic frames — no camera needed
 *
 * Detection: MediaPipe tasks-vision ObjectDetector, efficientdet-lite0
 * int8 (~4.4MB), VIDEO mode, drawn on an overlay canvas. Runs entirely
 * in-browser — the Nest's edge tier; server only serves static files.
 *
 * Bench: ?bench=N runs N detections, reports fps + inference ms
 * (p50/p95), model, and device UA in-page; POSTs the row to MDDB
 * (ada-ha-scenario-reports bench/edge-*) via the same-origin
 * /apps/eye-mddb route so device capability is measured, not guessed.
 *
 * Publish: ?pub=N rewrites the eye/latest doc every N seconds with the
 * freshest detection list — the read side of Ada's ada_look tool.
 * Off by default; point a cast at ?src=...&pub=10 to give Ada eyes.
 */
import { FilesetResolver, ObjectDetector } from '../vendor/mediapipe/vision_bundle.mjs';

const params = new URLSearchParams(location.search);
const src = params.get('src') || 'me';
const benchN = parseInt(params.get('bench') || '0', 10);
const pubSec = parseFloat(params.get('pub') || '0');
const MODEL = 'efficientdet_lite0_int8';
// Same-origin MDDB write lane (edge route eye-mddb -> mddb /v1/add,
// tailnet-identity gated). Cross-origin to idc03 never worked — there is
// no /mddb mount on that edge.
const MDDB = '/apps/eye-mddb/v1';

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
  } else if (src.startsWith('vms:')) {
    const name = src.slice(4);
    srcEl.textContent = `source: vms:${name} (fresh xmeye snap)`;
    return `vms:${name}`;
  } else if (src.startsWith('snap:')) {
    const name = src.slice(5);
    // Snapshot refresh -> draw frames onto a synthetic video-like path:
    // reuse an <img> polled every 2s, detect on the drawn image.
    // <zone>/<key> resolves to a camwall last-good thumb (xmeye/DVR
    // channels live there — the puller IS the xmeye proxy); a bare name
    // goes to frigate latest.jpg as before.
    srcEl.textContent = `source: snap:${name} (${name.includes('/') ? 'camwall' : '2s poll'})`;
    return name;
  }
  throw new Error(`unknown src "${src}" — me | cam:<name> | ` +
    `snap:<name|zone/key> | vms:<channel> | test`);
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
    snapImg.style.cssText =
      'position:absolute;inset:0;width:100%;height:100%;object-fit:contain;';
    document.getElementById('stage').insertBefore(snapImg, overlay);
  }
  let url;
  if (name.startsWith('vms:')) {
    // Fresh xmeye capture through the same-origin vms-snap proxy
    // (mn01 shim clicks the channel in the VMS desktop ~10s/frame).
    url = `/apps/vms-snap/snap?ch=${encodeURIComponent(name.slice(4))}&native=1&r=${Date.now()}`;
  } else if (name.includes('/')) {
    // <zone>/<key> — camwall last-good thumb (never 404s while the
    // puller ran once; staleness is the puller's honesty model).
    url = `/apps/camwall/data/${name}.jpg?t=${Date.now()}`;
  } else {
    url = `/frigate/api/${name}/latest.jpg?t=${Date.now()}`;
  }
  await new Promise((res) => {
    snapImg.onload = res; snapImg.onerror = res;
    snapImg.src = url;
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
  // Best-effort record — same-origin write lane; keep it non-fatal.
  try {
    const r = await fetch(`${MDDB}/add`, {
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
    if (!r.ok) benchEl.textContent = txt + `\nMDDB ${r.status}`;
  } catch (e) {
    benchEl.textContent = txt + `\nMDDB ${e.message}`;
  }
}

// --- ada_look read side --------------------------------------------------
// ?pub=N rewrites ada-ha-scenario-reports/eye:latest every N seconds with
// the freshest detections. Fixed key, small doc — the ada tool reads this
// one doc ("what do you see") instead of scanning. Actions on detections
// stay behind the confirm-gated tools; this doc is read-only state.
let lastPub = 0;
async function publish(dets) {
  const now = Date.now();
  if (!pubSec || now - lastPub < pubSec * 1000) return;
  lastPub = now;
  const ts = new Date(now).toISOString();
  const list = dets.map(d => ({
    cls: d.categories?.[0]?.categoryName ?? '?',
    score: +(d.categories?.[0]?.score ?? 0).toFixed(3),
    box: d.boundingBox ? [d.boundingBox.originX, d.boundingBox.originY,
                        d.boundingBox.width, d.boundingBox.height]
                       .map(v => Math.round(v)) : null,
  }));
  const counts = {};
  for (const d of list) counts[d.cls] = (counts[d.cls] || 0) + 1;
  const summary = Object.entries(counts)
    .map(([k, n]) => `${k}×${n}`).join(', ') || 'nothing detected';
  const payload = { ts, src, model: MODEL, detections: list,
                    ua: navigator.userAgent.slice(0, 160),
                    pub_s: pubSec };
  try {
    await fetch(`${MDDB}/add`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        collection: 'ada-ha-scenario-reports',
        key: 'eye/latest',
        contentMd:
          `# eye/latest — ${ts}\n\n` +
          `**${list.length} detection(s) on \`${src}\`** — ${summary}.\n\n` +
          '```json\n' + JSON.stringify(payload, null, 2) + '\n```\n',
        meta: { kind: ['state'], domain: ['eye'], attribute: ['detections'],
                title: ['eye — latest detections'], updated: [ts],
                fresh_for: ['1h'], status: ['active'], lang: ['en'],
                written_by: ['eye-page'], src: [src] },
      }),
    });
  } catch (_) { /* non-fatal — the overlay is the primary output */ }
}

async function loop(snapName, modelLoadMs) {
  const samples = [];
  const tick = async () => {
    // Ticks are inherently serial — the next one is only scheduled when
    // this one returns, so a slow vms-snap capture (~10s) can never stack.
    const srcEl2 = snapName ? await snapFrame(snapName) : vid;
    const ready = snapName === '__test__' ? true
                : snapName ? (snapImg?.naturalWidth > 0)
                : (vid.readyState >= 2 && vid.videoWidth > 0);
    if (ready) {
      const t0 = performance.now();
      // VIDEO-mode API accepts any ImageSource (video/img/canvas).
      const res = detector.detectForVideo(srcEl2, t0);
      const ms = performance.now() - t0;
      const dets = res.detections || [];
      draw(dets);
      publish(dets);   // throttled internally; fire-and-forget
      if (bench) {
        samples.push(ms);
        if (samples.length <= benchN) {
          benchEl.textContent =
            `bench ${samples.length}/${benchN}  last ${ms.toFixed(0)}ms`;
          if (samples.length === benchN) { bench = false; await finishBench(samples, modelLoadMs); }
        }
      } else {
        statEl.textContent = `${dets.length} obj · ${ms.toFixed(0)}ms` +
          (pubSec ? ` · pub ${pubSec}s` : '');
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
