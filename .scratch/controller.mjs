
// ?engine=yolo — rebuild path: no on-device MediaPipe. The phone is a bare
// camera: frames POST to input-bridge /frame (screen 0, token "gesture"),
// a yolo-gesture service (hand_yolov8n.pt) turns the hand bounding box
// into {type:"gesture"} msgs and publishes straight into the relay as a
// controller. This page only uploads frames; the screen gets its cursor
// from the service. Box world: no pinch — dwell clicks, 2 hands = grab.
const QS = new URLSearchParams(location.search);
const ENGINE = QS.get('engine') === 'yolo' ? 'yolo' : 'mediapipe';
const YOLO_UPLINK_MS = 300;              // ~3.3fps — pointer cadence

let FilesetResolver, HandLandmarker, FaceLandmarker, PoseLandmarker;
if (ENGINE !== 'yolo') {
  ({ FilesetResolver, HandLandmarker, FaceLandmarker, PoseLandmarker } =
    await import('/apps/vendor/mediapipe/vision_bundle.mjs'));
}

const WASM_DIR   = '/apps/vendor/mediapipe/';
const MODEL_HAND = '/apps/vendor/mediapipe/hand_landmarker.task';
const MODEL_FACE = '/apps/vendor/mediapipe/face_landmarker.task';
const MODEL_POSE = '/apps/vendor/mediapipe/pose_landmarker_lite.task';
// ada_v2 constants (docs/kb/gesture-ui-options.md) — phone sends RAW
// normalized coords; SENSITIVITY/LERP are applied screen-side.
const PINCH_DIST   = 0.05;   // dist(lm4,lm8) normalized
const EMIT_MIN_MS  = 50;     // ~20 Hz cursor cap
const HAND_CONNECTIONS = [
  [0,1],[1,2],[2,3],[3,4],
  [0,5],[5,6],[6,7],[7,8],
  [5,9],[9,10],[10,11],[11,12],
  [9,13],[13,14],[14,15],[15,16],
  [13,17],[17,18],[18,19],[19,20],
  [0,17],
];

const $ = id => document.getElementById(id);
const video = $('cam'), canvas = $('overlay'), ctx = canvas.getContext('2d'),
      stage = $('stage');
const statusEl = $('status'), hudFps = $('hud-fps'), hudHand = $('hud-hand'),
      hudPose = $('hud-pose'), hudTx = $('hud-tx');

let landmarker = null, faceLm = null, poseLm = null, visionP = null, stream = null;
let flipX = true;                    // mirror so the pointer matches the hand
let lastVideoTime = -1, lastEmit = 0, txCount = 0;
let handState = {}, lastLm = null;   // per-hand {pinch,fist} edge state
const want = { hands: true, face: true, pose: true };
const faceState = { y: null, x: null, t: 0, xs: [], nodT: 0, shakeT: 0 };
const poseState = { y: null, t: 0, jumpT: 0, 'arm-up-L': false, 'arm-up-R': false };
let frames = 0, fpsT = performance.now();

function status(text, cls) { statusEl.textContent = text; statusEl.className = cls; }

/* ---------------- ws ---------------- */
const wsUrl = QS.get('ws')
  || `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/apps/gesture-live/ws?role=controller`;
let ws = null, wsOpen = false, wsRetry = 0;
function connectWs() {
  try { ws = new WebSocket(wsUrl); } catch (e) { status('ws url bad: ' + e, 'err'); return; }
  ws.onopen = () => { wsOpen = true; wsRetry = 0; renderStatus(); };
  ws.onclose = ws.onerror = () => {
    wsOpen = false; renderStatus();
    setTimeout(connectWs, Math.min(8000, 500 * 2 ** wsRetry++));
  };
}
function send(obj) {
  if (wsOpen && ws.readyState === 1) { ws.send(JSON.stringify(obj)); txCount++; hudTx.textContent = 'tx ' + txCount; }
}

/* ---------------- mediapipe ---------------- */
// three sensors, each toggleable — landmarkers init lazily per `want`
async function initLandmarkers() {
  const vision = await (visionP ||= FilesetResolver.forVisionTasks(WASM_DIR));
  const jobs = [];
  if (want.hands && !landmarker)
    jobs.push(HandLandmarker.createFromOptions(vision, {
      baseOptions: { modelAssetPath: MODEL_HAND, delegate: 'GPU' },
      runningMode: 'VIDEO', numHands: 2 }).then(m => landmarker = m));
  if (want.face && !faceLm)
    jobs.push(FaceLandmarker.createFromOptions(vision, {
      baseOptions: { modelAssetPath: MODEL_FACE, delegate: 'GPU' },
      runningMode: 'VIDEO', outputFaceBlendshapes: true }).then(m => faceLm = m));
  if (want.pose && !poseLm)
    jobs.push(PoseLandmarker.createFromOptions(vision, {
      baseOptions: { modelAssetPath: MODEL_POSE, delegate: 'GPU' },
      runningMode: 'VIDEO', numPoses: 1 }).then(m => poseLm = m));
  await Promise.all(jobs);
}

async function startCamera() {
  if (!navigator.mediaDevices?.getUserMedia) {
    status('getUserMedia unavailable — needs HTTPS (or PWA camera denied)', 'err');
    return;
  }
  let constraints = { video: { facingMode: 'user', width: { ideal: 1280 }, height: { ideal: 720 } }, audio: false };
  try {
    stream = await navigator.mediaDevices.getUserMedia(constraints);
  } catch (e) {
    console.warn('environment camera failed, retrying default:', e);
    stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
  }
  video.srcObject = stream;
  await video.play();
  if (ENGINE === 'yolo') {
    status('yolo: frames → bridge', 'ok');
    requestAnimationFrame(yoloLoop);
    return;
  }
  if ((want.hands && !landmarker) || (want.face && !faceLm) || (want.pose && !poseLm)) {
    status('loading models (hands+face+pose)…', 'warn');
    await initLandmarkers();
  }
  status('tracking', 'ok');
  requestAnimationFrame(loop);
}

/* ---------------- yolo engine: bare camera uplink ---------------- */
// The yolo-gesture service polls the bridge's latest frame, detects the
// hand bbox, and publishes {type:"gesture"} into the relay itself — this
// page never sees a pointer coordinate, it just ships frames.
let lastUp = 0, upOk = 0, upErr = 0;
function yoloLoop() {
  requestAnimationFrame(yoloLoop);
  if (video.readyState < 2 || !video.videoWidth) return;
  const now = performance.now();
  frames++;
  if (now - fpsT > 1000) { hudFps.textContent = 'cam ' + frames + 'fps'; frames = 0; fpsT = now; }
  hudHand.textContent = 'up ' + upOk + (upErr ? ' err ' + upErr : '');
  hudPose.textContent = 'engine yolo';
  if (now - lastUp < YOLO_UPLINK_MS) return;
  lastUp = now;
  const w = 480, h = Math.round(w * video.videoHeight / video.videoWidth);
  const c = document.createElement('canvas');
  c.width = w; c.height = h;
  c.getContext('2d').drawImage(video, 0, 0, w, h);
  fetch('/api/input-bridge/frame', {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ screen: 0, token: 'gesture',
      state: 'gesture-uplink', data: c.toDataURL('image/jpeg', 0.6) }),
  }).then(r => { r.ok ? upOk++ : upErr++; }).catch(() => upErr++);
}

/* ---------------- gestures ---------------- */
const dist = (a, b) => Math.hypot(a.x - b.x, a.y - b.y, (a.z || 0) - (b.z || 0));
const folded = (lm, tip, mcp) => dist(lm[tip], lm[0]) < dist(lm[mcp], lm[0]);
const fistOf = lm => folded(lm, 8, 5) && folded(lm, 12, 9) && folded(lm, 16, 13) && folded(lm, 20, 17); // thumb not counted

/* landmark coords are normalized to the RAW video frame; the video shows
   object-fit:cover (cropped). Map through the same cover crop so the
   skeleton sits on the hand picture. Mirror is the CSS flip on
   #cam + #overlay together — always draw in unmirrored space. */
function coverMap(nx, ny) {
  const vw = video.videoWidth || 1, vh = video.videoHeight || 1;
  const sw = stage.clientWidth || 1, sh = stage.clientHeight || 1;
  const s = Math.max(sw / vw, sh / vh);
  return [nx * vw * s + (sw - vw * s) / 2,
          ny * vh * s + (sh - vh * s) / 2];
}
function drawSkeleton(lm) {
  ctx.strokeStyle = '#22d3ee'; ctx.lineWidth = 3;
  ctx.beginPath();
  for (const [a, b] of HAND_CONNECTIONS) {
    const [x1, y1] = coverMap(lm[a].x, lm[a].y);
    const [x2, y2] = coverMap(lm[b].x, lm[b].y);
    ctx.moveTo(x1, y1); ctx.lineTo(x2, y2);
  }
  ctx.stroke();
  ctx.fillStyle = '#e0f2fe';
  for (const p of lm) {
    const [px, py] = coverMap(p.x, p.y);
    ctx.beginPath(); ctx.arc(px, py, 3, 0, 7); ctx.fill();
  }
}

function loop() {
  requestAnimationFrame(loop);
  if (!landmarker || video.readyState < 2 || !video.videoWidth) return;
  if (video.currentTime === lastVideoTime) return;
  lastVideoTime = video.currentTime;

  if (canvas.width !== stage.clientWidth || canvas.height !== stage.clientHeight) {
    canvas.width = stage.clientWidth; canvas.height = stage.clientHeight;
  }
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  const res = (want.hands && landmarker)
    ? landmarker.detectForVideo(video, performance.now()) : { landmarks: [] };
  const hands = res.landmarks || [];
  frames++;
  const now = performance.now();
  if (now - fpsT > 1000) { hudFps.textContent = 'fps ' + frames; frames = 0; fpsT = now; }
  hudHand.textContent = want.hands
    ? (hands.length ? 'hands ' + hands.length : 'no hand') : 'hands off';

  const seen = {}, poses = [];
  for (let i = 0; i < hands.length; i++) {
    const lm = hands[i];
    const hand = res.handednesses?.[i]?.[0]?.categoryName || 'Right';
    seen[hand] = true;
    drawSkeleton(lm);
    lastLm = lm;

    const pinch = dist(lm[4], lm[8]) < PINCH_DIST;
    const fist = fistOf(lm);
    const st = handState[hand] || (handState[hand] = { pinch: false, fist: false });
    poses.push(hand[0] + ':' + (fist ? 'FIST' : pinch ? 'PINCH' : 'open'));

    // dwell debounce — a pose must HOLD across frames to count; single-frame
    // landmark flicker was forging fists/pinches (phantom strikes = scream)
    st.fN = fist ? (st.fN || 0) + 1 : 0;
    st.pN = pinch ? (st.pN || 0) + 1 : 0;
    st.uN = !fist ? (st.uN || 0) + 1 : 0;
    const fistOn = st.fN >= 3, fistOff = st.uN >= 2, pinchOn = st.pN >= 3;

    const tipX = flipX ? 1 - lm[8].x : lm[8].x;
    st.sx = st.sx === undefined ? tipX : st.sx + (tipX - st.sx) * 0.35;
    const base = () => ({
      type: 'gesture', hand,
      x: st.sx,                            // smoothed index tip
      y: lm[8].y,
      wx: flipX ? 1 - lm[0].x : lm[0].x,  // wrist (drag anchor)
      wy: lm[0].y,
    });

    // edge events go out immediately; cursor frames throttled to ~20Hz
    if (pinchOn && !st.pinch) { st.pinch = true; send({ ...base(), action: 'pinch' }); }
    if (!pinchOn && st.pinch) st.pinch = false;
    if (fistOn && !st.fist) { st.fist = true; send({ ...base(), action: 'fist_start' }); }
    if (fistOff && st.fist) { st.fist = false; send({ ...base(), action: 'fist_end' }); }

    // swipe: open hand crossing >35% of frame in <350ms -> style change.
    // Smoothed x (EMA) kills landmark flicker; a >150ms tracking gap
    // clears the window — edge dropout+re-detect can't fake a swipe.
    const lastXsT = st.xs?.length ? st.xs[st.xs.length - 1][0] : 0;
    if (now - lastXsT > 150) (st.xs ||= []).length = 0;
    (st.xs ||= []).push([now, st.sx]);
    while (st.xs.length && now - st.xs[0][0] > 350) st.xs.shift();
    if (st.xs.length > 3 && !st.fist && now - (st.swipeT || 0) > 700) {
      const dx = st.xs[st.xs.length - 1][1] - st.xs[0][1];
      if (Math.abs(dx) > 0.35) {
        st.swipeT = now; st.xs.length = 0;
        send({ type: 'body', evt: dx > 0 ? 'swipe-R' : 'swipe-L', val: 1 });
      }
    }

    if (now - lastEmit >= EMIT_MIN_MS) send(base());
  }
  if (now - lastEmit >= EMIT_MIN_MS) lastEmit = now;
  if (!hands.length) handState = {};
  for (const h in handState) if (!seen[h]) delete handState[h];

  /* ---------------- face ---------------- */
  // blendshapes -> smile/mouth/brow edges; nose-tip motion -> nod/shake.
  // Emits {type:"body", evt, val} — receivers map via their own bindings.
  const bodyEmit = (evt, val = 1, cd = 500) => {
    // retrigger cooldown — stops blendshape/edge flapping screaming
    if (now - (bodyEmit.last?.[evt] || 0) < cd) return;
    (bodyEmit.last ||= {})[evt] = now;
    send({ type: 'body', evt, val }); poses.push('!' + evt);
  };
  // deadband edge: fires once on `on`, cannot re-fire until `off` clears it —
  // a value hovering AT the threshold emits one shot then stays quiet.
  const edge = (state, evt, on, off, cd) => {
    if (!state['a_' + evt]) {
      if (on) { state['a_' + evt] = true; bodyEmit(evt, 1, cd); }
    } else if (off) state['a_' + evt] = false;
  };
  if (want.face && faceLm) {
    const fr = faceLm.detectForVideo(video, now);
    const fl = fr.faceLandmarks?.[0];
    const cats = fr.faceBlendshapes?.[0]?.categories || [];
    const bv = n => cats.find(c => c.categoryName === n)?.score || 0;
    if (fl) {
      const nose = fl[4] || fl[1];
      const dt = Math.max(1, now - faceState.t);
      const vy = (nose.y - (faceState.y ?? nose.y)) / dt * 1000;
      if (vy > 0.9 && now - faceState.nodT > 500) { faceState.nodT = now; bodyEmit('nod'); }
      faceState.xs.push([now, flipX ? 1 - nose.x : nose.x]);
      while (faceState.xs.length && now - faceState.xs[0][0] > 600) faceState.xs.shift();
      let flips = 0, dir = 0;
      for (let i = 1; i < faceState.xs.length; i++) {
        const d = faceState.xs[i][1] - faceState.xs[i - 1][1];
        if (Math.abs(d) > 0.004) {
          const s = Math.sign(d);
          if (dir && s !== dir) flips++;
          dir = s;
        }
      }
      if (flips >= 2 && now - faceState.shakeT > 700) { faceState.shakeT = now; bodyEmit('shake'); }
      {
        const sm = bv('mouthSmileLeft') + bv('mouthSmileRight');
        edge(faceState, 'smile', sm > 1.0, sm < 0.65);
        const jaw = bv('jawOpen');
        edge(faceState, 'mouth', jaw > 0.5, jaw < 0.32);
        const br = bv('browInnerUp');
        edge(faceState, 'brow', br > 0.55, br < 0.38);
      }
      faceState.y = nose.y; faceState.t = now;
      const [px, py] = coverMap(nose.x, nose.y);
      ctx.fillStyle = '#f472b6';
      ctx.beginPath(); ctx.arc(px, py, 7, 0, 7); ctx.fill();
    }
  }

  /* ---------------- body / pose ---------------- */
  const POSE_CONNECTIONS = [[11,12],[11,13],[13,15],[12,14],[14,16],
                            [11,23],[12,24],[23,24]];
  if (want.pose && poseLm) {
    const pr = poseLm.detectForVideo(video, now);
    const pl = pr.landmarks?.[0];
    if (pl) {
      const mid = (a, b) => ({ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 });
      const sh = mid(pl[11], pl[12]), hip = mid(pl[23], pl[24]);
      // jump: hips move UP fast (y decreases); lean: continuous shoulder x
      const dt = Math.max(1, now - poseState.t);
      const vy = (hip.y - (poseState.y ?? hip.y)) / dt * 1000;
      if (vy < -1.2 && now - poseState.jumpT > 800) { poseState.jumpT = now; bodyEmit('jump'); }
      poseState.y = hip.y; poseState.t = now;
      // arm raised = deliberate solo trigger: fires once per 2.5s max and
      // re-arms only when the wrist comes clearly BELOW the shoulder
      edge(poseState, 'arm-up-L',
           pl[15].y < pl[11].y - 0.08, pl[15].y > pl[11].y + 0.10, 2500);
      edge(poseState, 'arm-up-R',
           pl[16].y < pl[12].y - 0.08, pl[16].y > pl[12].y + 0.10, 2500);
      if (now - lastEmit >= EMIT_MIN_MS)
        send({ type: 'body', evt: 'lean', val: Math.min(1, Math.max(0, flipX ? 1 - sh.x : sh.x)) });
      ctx.strokeStyle = '#4ade80'; ctx.lineWidth = 3;
      ctx.beginPath();
      for (const [a, b] of POSE_CONNECTIONS) {
        const [x1, y1] = coverMap(pl[a].x, pl[a].y);
        const [x2, y2] = coverMap(pl[b].x, pl[b].y);
        ctx.moveTo(x1, y1); ctx.lineTo(x2, y2);
      }
      ctx.stroke();
    }
  }

  hudPose.textContent = poses.join(' · ') || 'pose –';
}

/* ---------------- ui ---------------- */
function renderStatus() {
  if (!stream) return status('idle — tap Start camera', 'warn');
  if (ENGINE === 'yolo')
    return status('yolo: uplinking frames — pointer comes from the service', 'ok');
  if (!landmarker) return status('loading hand model…', 'warn');
  status(wsOpen ? 'tracking · relay connected' : 'tracking · relay OFFLINE (retrying)', wsOpen ? 'ok' : 'err');
}
$('btn-start').onclick = () => startCamera().catch(e => status('camera/model: ' + e.message, 'err'));
$('btn-flip').onclick = e => {
  flipX = !flipX;
  e.target.textContent = 'Mirror X: ' + (flipX ? 'on' : 'off');
  e.target.classList.toggle('on', flipX);
  stage.classList.toggle('mirror', flipX);
};
for (const [id, key, label] of [['btn-hands','hands','Hands'],
                                ['btn-face','face','Face'],
                                ['btn-pose','pose','Body']]) {
  $(id).onclick = e => {
    want[key] = !want[key];
    e.target.textContent = label + ': ' + (want[key] ? 'on' : 'off');
    e.target.classList.toggle('on', want[key]);
    if (want[key]) initLandmarkers().catch(err => status('model: ' + err.message, 'err'));
  };
}
$('btn-pinch').onclick = () => {
  const lm = lastLm;
  send({ type: 'gesture', action: 'pinch',
         x: lm ? (flipX ? 1 - lm[8].x : lm[8].x) : 0.5,
         y: lm ? lm[8].y : 0.5,
         wx: lm ? (flipX ? 1 - lm[0].x : lm[0].x) : 0.5,
         wy: lm ? lm[0].y : 0.5 });
};
/* ---------------- voice -> screen sci-fi FX ---------------- */
// mic -> 12kHz mono PCM -> base64 JSON on the relay; the screen module
// runs it through a random sci-fi chain there.
let vStream = null, vCtx = null, vSrc = null, vProc = null;
function b64FromI16(i16) {
  const u8 = new Uint8Array(i16.buffer);
  let s = '';
  for (let i = 0; i < u8.length; i += 8192)
    s += String.fromCharCode.apply(null, u8.subarray(i, i + 8192));
  return btoa(s);
}
// PUSH-TO-TALK: voice streams only while the button is physically held —
// an unattended mic can never re-capture the screen's own sound (howl).
let vAuto = 0;
function stopVoice(btn) {
  if (!vStream) return;
  clearTimeout(vAuto);
  vStream.getTracks().forEach(t => t.stop());
  vProc.disconnect(); vSrc.disconnect(); vCtx.close();
  vStream = vCtx = vSrc = vProc = null;
  btn.classList.remove('on'); btn.textContent = '🎤 hold to talk';
}
async function startVoice(btn) {
  if (vStream) return;
  try {
    vStream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true } });
    vCtx = new AudioContext();
    vSrc = vCtx.createMediaStreamSource(vStream);
    vProc = vCtx.createScriptProcessor(2048, 1, 1);
    const ratio = vCtx.sampleRate / 12000;
    let acc = [];
    vProc.onaudioprocess = ev => {
      const d = ev.inputBuffer.getChannelData(0);
      for (let i = 0; i + 1 < d.length; i += ratio)
        acc.push((d[i | 0] + d[(i | 0) + 1]) * 0.5);
      while (acc.length >= 1200) {           // ~100ms chunks
        const chunk = acc.splice(0, 1200), i16 = new Int16Array(chunk.length);
        let rms = 0;
        for (let j = 0; j < chunk.length; j++) {
          i16[j] = Math.max(-32768, Math.min(32767, chunk[j] * 32767 | 0));
          rms += chunk[j] * chunk[j];
        }
        if (rms / chunk.length > 0.0004)
          send({ type: 'voice', sr: 12000, pcm: b64FromI16(i16) });
      }
    };
    // ScriptProcessor must reach destination to run — through a silent gain
    const mute = vCtx.createGain(); mute.gain.value = 0;
    vSrc.connect(vProc); vProc.connect(mute).connect(vCtx.destination);
    btn.classList.add('on'); btn.textContent = '🎤 TALKING…';
    // hard cap: never stream >8s without a fresh press (stuck-hold guard)
    vAuto = setTimeout(() => stopVoice(btn), 8000);
  } catch (err) { status('mic: ' + err.message, 'err'); }
}
{
  const vb = $('btn-voice');
  vb.textContent = '🎤 hold to talk';
  vb.oncontextmenu = e => e.preventDefault();
  vb.onpointerdown = e => {
    e.preventDefault();
    try { vb.setPointerCapture(e.pointerId); } catch {}
    startVoice(vb);
  };
  vb.onpointerup = vb.onpointercancel = vb.onlostpointercapture =
    () => stopVoice(vb);
  // iOS fallbacks — a dropped pointerup must not leave the mic streaming
  window.addEventListener('touchend', () => stopVoice(vb), { passive: true });
  window.addEventListener('touchcancel', () => stopVoice(vb), { passive: true });
  window.addEventListener('blur', () => stopVoice(vb));
  document.addEventListener('visibilitychange',
    () => { if (document.hidden) stopVoice(vb); });
}

$('btn-screen').onclick = () => { location.href = '/apps/gesture/screen'; };

if (ENGINE === 'yolo') {
  // no on-device models in yolo mode — the toggles would init MediaPipe
  for (const id of ['btn-hands', 'btn-face', 'btn-pose'])
    $(id).style.display = 'none';
  $('note').textContent =
    'YOLO engine: this phone is only a camera — frames go to input-bridge, ' +
    'a yolo-gesture service detects the hand bounding box and drives the ' +
    'screen cursor. Point with an open hand; hold still to click; two ' +
    'hands = grab. Service must run with YOLO_FRAME_URL pointing at ' +
    'bridge /frame?screen=0&token=gesture and POINTER_SINK at the relay.';
}

connectWs();
status('idle — tap Start camera', 'warn');
