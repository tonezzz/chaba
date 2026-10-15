
/* ada_v2 gesture pipeline — screen side.
 * Phone sends RAW normalized coords (0–1, X mirror-flipped). Here we apply
 * SENSITIVITY -> clamp -> LERP -> snap-hysteresis -> snap glow, then the
 * pinch/fist state machines. Constants from docs/kb/gesture-ui-options.md. */
const SENSITIVITY = 2.0;      // center 50% of camera maps to full screen
const LERP = 0.2;
const SNAP_THRESHOLD = 50;    // px — lock to element center
const UNSNAP_THRESHOLD = 100; // px — release hysteresis
const DRAG_DEADZONE = 0.5;    // px wrist delta

const $ = id => document.getElementById(id);
const cursor = $('gcursor'), statusEl = $('status');

/* ------- draggable windows (mouse path too, for testing) ------- */
// wins[id].{x,y} = left/top within #surface; windows keep their HTML % pose
// until first measured, then switch to px.
const surface = $('surface');
const wins = {};
for (const el of document.querySelectorAll('.gwin')) {
  const r = el.getBoundingClientRect(), s = surface.getBoundingClientRect();
  const x = r.left - s.left, y = r.top - s.top;
  el.style.left = x + 'px'; el.style.top = y + 'px';
  wins[el.id] = { el, x, y };
}
function placeWin(id, x, y) {
  const w = wins[id], el = w.el;
  w.x = Math.min(Math.max(x, 0), surface.clientWidth - el.offsetWidth);
  w.y = Math.min(Math.max(y, 0), surface.clientHeight - el.offsetHeight);
  el.style.left = w.x + 'px'; el.style.top = w.y + 'px';
}
let mouseDrag = null;
document.addEventListener('mousedown', e => {
  const w = e.target.closest('.gwin');
  if (w && e.target.closest('[data-drag-handle]')) {
    const r = w.getBoundingClientRect();
    mouseDrag = { id: w.id, dx: e.clientX - r.left, dy: e.clientY - r.top };
  }
});
document.addEventListener('mousemove', e => {
  if (!mouseDrag) return;
  const s = surface.getBoundingClientRect();
  placeWin(mouseDrag.id, e.clientX - s.left - mouseDrag.dx, e.clientY - s.top - mouseDrag.dy);
});
document.addEventListener('mouseup', () => mouseDrag = null);

/* ------- cursor state ------- */
const pos = { x: innerWidth / 2, y: innerHeight / 2 };     // smoothed
const target = { x: innerWidth / 2, y: innerHeight / 2 };  // raw target
let snapped = null;          // element the cursor is snapped to
let pinchVisual = 0;
const norm = v => Math.min(1, Math.max(0, (v - 0.5) * SENSITIVITY + 0.5));

function snapScan(fx, fy) {
  let best = null, bestD = SNAP_THRESHOLD;
  for (const el of document.querySelectorAll('button, a, select, [role="button"], .tile')) {
    const r = el.getBoundingClientRect();
    if (!r.width) continue;
    const d = Math.hypot(r.left + r.width / 2 - fx, r.top + r.height / 2 - fy);
    if (d < bestD) { bestD = d; best = { el, cx: r.left + r.width / 2, cy: r.top + r.height / 2 }; }
  }
  if (snapped && Math.hypot(snapped.cx - fx, snapped.cy - fy) > UNSNAP_THRESHOLD) {
    snapped.el.classList.remove('snap-highlight'); snapped = null;
  }
  if (!snapped && best) { snapped = best; best.el.classList.add('snap-highlight'); }
  if (snapped) { const r = snapped.el.getBoundingClientRect(); snapped.cx = r.left + r.width / 2; snapped.cy = r.top + r.height / 2; }
  return snapped;
}

function frame() {
  requestAnimationFrame(frame);
  pos.x += (target.x - pos.x) * LERP;
  pos.y += (target.y - pos.y) * LERP;
  const s = snapScan(pos.x, pos.y);
  const fx = s ? s.cx : pos.x, fy = s ? s.cy : pos.y;
  cursor.style.left = fx + 'px'; cursor.style.top = fy + 'px';
  if (pinchVisual > 0 && --pinchVisual === 0) cursor.classList.remove('pinch');
}
requestAnimationFrame(frame);

/* ------- actions ------- */
function doPinch() {
  const s = snapped;
  const fx = s ? s.cx : pos.x, fy = s ? s.cy : pos.y;
  pinchVisual = 14; cursor.classList.add('pinch');
  const el = document.elementFromPoint(fx, fy);
  const btn = el && el.closest('button, a, [role="button"]');
  if (btn) btn.click();
  else if (el) el.click();
}

/* dwell-click for box-driven pointers (src:"yolo") — no landmark pinch
 * exists in the YOLO rebuild, so parking the cursor on the same snapped
 * element for DWELL_MS fires the click instead. MediaPipe-sourced frames
 * keep the pinch-only contract. */
const DWELL_MS = 700, DWELL_COOLDOWN = 1200;
let dwellEl = null, dwellT = 0, dwellCool = 0, yoloSrc = false;
setInterval(() => {
  if (!yoloSrc || !snapped || dragId !== null) { dwellEl = null; return; }
  const now = performance.now();
  if (snapped.el !== dwellEl) { dwellEl = snapped.el; dwellT = now; return; }
  if (now - dwellT >= DWELL_MS && now > dwellCool) {
    dwellCool = now + DWELL_COOLDOWN; dwellT = now + 1e9;
    doPinch();                          // same hit-test/click path
  }
}, 120);

let dragId = null, lastWrist = null;
function fistStart(m) {
  const s = snapped;
  const fx = s ? s.cx : pos.x, fy = s ? s.cy : pos.y;
  for (const id in wins) {
    const r = wins[id].el.getBoundingClientRect();
    if (fx >= r.left && fx <= r.right && fy >= r.top && fy <= r.bottom) {
      dragId = id; wins[id].el.classList.add('grabbing');
      lastWrist = { x: norm(m.wx) * innerWidth, y: norm(m.wy) * innerHeight };
      return;
    }
  }
  lastWrist = null;
}
function fistMove(m) {
  if (dragId === null || m.wx === undefined) return;
  const wx = norm(m.wx) * innerWidth, wy = norm(m.wy) * innerHeight;
  if (!lastWrist) { lastWrist = { x: wx, y: wy }; return; }
  const dx = wx - lastWrist.x, dy = wy - lastWrist.y;
  lastWrist = { x: wx, y: wy };
  if (Math.abs(dx) > DRAG_DEADZONE || Math.abs(dy) > DRAG_DEADZONE)
    placeWin(dragId, wins[dragId].x + dx, wins[dragId].y + dy);
}
function fistEnd() {
  if (dragId) wins[dragId].el.classList.remove('grabbing');
  dragId = null; lastWrist = null;
}

/* ------- cast to TV (mn01 yolo service via Caddy) ------- */
async function loadTvs() {
  const sel = $('tv-list');
  try {
    const r = await fetch('/apps/yolo/api/tvs');
    const j = await r.json();
    sel.innerHTML = '';
    for (const t of j.tvs || []) {
      const o = document.createElement('option'); o.value = o.textContent = t; sel.appendChild(o);
    }
    if (!sel.options.length) sel.innerHTML = '<option value="">no media_players</option>';
  } catch (e) {
    sel.innerHTML = '<option value="">tvs fetch failed</option>';
  }
}
$('btn-cast').addEventListener('click', async () => {
  const target = $('tv-list').value;
  $('cast-status').textContent = 'casting → ' + target + ' …';
  try {
    const r = await fetch('/apps/yolo/api/cast?target=' + encodeURIComponent(target));
    const j = await r.json();
    $('cast-status').textContent = j.ok ? 'cast ok → ' + j.target : ('cast failed: ' + (j.error || r.status));
  } catch (e) {
    $('cast-status').textContent = 'cast failed: ' + e.message;
  }
});
loadTvs();

/* ------- ws ------- */
const wsUrl = new URLSearchParams(location.search).get('ws')
  || `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/apps/gesture-live/ws?role=screen`;
let ws, wsRetry = 0, rx = 0, rxT = performance.now(), rxRate = 0, peers = { controllers: 0, screens: 0 };

function status(t, c) { statusEl.textContent = t; statusEl.className = c; }
function renderStatus() {
  if (peers.controllers > 0) status(`controller linked · ${rxRate}/s`, 'ok');
  else status('relay up · waiting for controller — open /apps/gesture/ on the phone', 'warn');
}
function connect() {
  ws = new WebSocket(wsUrl);
  ws.onopen = () => { wsRetry = 0; renderStatus(); };
  ws.onclose = ws.onerror = () => {
    status('relay OFFLINE (retrying)', 'err');
    setTimeout(connect, Math.min(8000, 500 * 2 ** wsRetry++));
  };
  ws.onmessage = ev => {
    let m; try { m = JSON.parse(ev.data); } catch { return; }
    if (m.type === 'peer') { peers = m; renderStatus(); return; }
    if (m.type !== 'gesture') return;
    if (m.gone) {                        // yolo: hand left the frame
      cursor.style.opacity = '0.25'; fistEnd(); dwellEl = null; return;
    }
    if (m.x === undefined) return;
    cursor.style.opacity = '';
    yoloSrc = m.src === 'yolo';
    rx++;
    const now = performance.now();
    if (now - rxT > 1000) { rxRate = rx; rx = 0; rxT = now; renderStatus(); }
    target.x = norm(m.x) * innerWidth;
    target.y = norm(m.y) * innerHeight;
    if (m.action === 'pinch') doPinch();
    else if (m.action === 'fist_start') fistStart(m);
    else if (m.action === 'fist_end') fistEnd();
    else if (dragId !== null) fistMove(m);   // cursor frames carry wrist too
  };
}
connect();
