/* Nest Percussion — sonifies fleet state from state.json.
   All drums synthesized in WebAudio — zero samples, zero network audio.
   Mapping contract (see scripts/ops-percussion-sync.py):
     bpm    ← ops events/hour (60-120)
     hosts  ← each host plays its role: kick(heavy)=idc*, snare=dell,
              tom=omen, hat=mn01, shaker=light nodes
     state  ← healthy=solid hit · degraded=ghost · error=accent+stutter
     alerts ← failing services = crash on bar downbeat */
"use strict";

const S = { ac: null, on: false, bpm: 72, step: 0, next: 0,
            state: null, timer: null, noise: null };
const LOOKAHEAD = 0.12, TICK_MS = 30;

/* ---------- synthesized voices ---------- */
function kick(t, v = 1) {
  const o = S.ac.createOscillator(), g = S.ac.createGain();
  o.frequency.setValueAtTime(150, t);
  o.frequency.exponentialRampToValueAtTime(38, t + 0.11);
  g.gain.setValueAtTime(v, t);
  g.gain.exponentialRampToValueAtTime(0.001, t + 0.35);
  o.connect(g).connect(S.ac.destination);
  o.start(t); o.stop(t + 0.4);
}
function snare(t, v = 1) {
  const n = noiseSrc(t, 0.18), bp = S.ac.createBiquadFilter(),
        g = S.ac.createGain();
  bp.type = "bandpass"; bp.frequency.value = 1800; bp.Q.value = 0.9;
  g.gain.setValueAtTime(0.7 * v, t);
  g.gain.exponentialRampToValueAtTime(0.001, t + 0.16);
  n.connect(bp).connect(g).connect(S.ac.destination);
  const o = S.ac.createOscillator(), g2 = S.ac.createGain();
  o.frequency.value = 185;
  g2.gain.setValueAtTime(0.35 * v, t);
  g2.gain.exponentialRampToValueAtTime(0.001, t + 0.1);
  o.connect(g2).connect(S.ac.destination); o.start(t); o.stop(t + 0.12);
}
function tom(t, v = 1) {
  const o = S.ac.createOscillator(), g = S.ac.createGain();
  o.frequency.setValueAtTime(220, t);
  o.frequency.exponentialRampToValueAtTime(95, t + 0.12);
  g.gain.setValueAtTime(0.6 * v, t);
  g.gain.exponentialRampToValueAtTime(0.001, t + 0.25);
  o.connect(g).connect(S.ac.destination); o.start(t); o.stop(t + 0.3);
}
function hat(t, v = 1, open = false) {
  const n = noiseSrc(t, 0.05), hp = S.ac.createBiquadFilter(),
        g = S.ac.createGain();
  hp.type = "highpass"; hp.frequency.value = 7000;
  g.gain.setValueAtTime(0.32 * v, t);
  g.gain.exponentialRampToValueAtTime(0.001, t + (open ? 0.25 : 0.04));
  n.connect(hp).connect(g).connect(S.ac.destination);
}
function shaker(t, v = 1) {
  const n = noiseSrc(t, 0.05), bp = S.ac.createBiquadFilter(),
        g = S.ac.createGain();
  bp.type = "bandpass"; bp.frequency.value = 5200; bp.Q.value = 3;
  g.gain.setValueAtTime(0.2 * v, t);
  g.gain.exponentialRampToValueAtTime(0.001, t + 0.06);
  n.connect(bp).connect(g).connect(S.ac.destination);
}
function crash(t, v = 0.8) {
  const n = noiseSrc(t, 1.2), hp = S.ac.createBiquadFilter(),
        g = S.ac.createGain();
  hp.type = "highpass"; hp.frequency.value = 4000;
  g.gain.setValueAtTime(v, t);
  g.gain.exponentialRampToValueAtTime(0.001, t + 1.0);
  n.connect(hp).connect(g).connect(S.ac.destination);
}
function noiseSrc(t, dur) {
  if (!S.noise) {
    const b = S.ac.createBuffer(1, S.ac.sampleRate * 1.2,
                                S.ac.sampleRate);
    const d = b.getChannelData(0);
    for (let i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1;
    S.noise = b;
  }
  const s = S.ac.createBufferSource();
  s.buffer = S.noise; s.start(t); s.stop(t + dur + 0.05);
  return s;
}

/* ---------- melodic voices (music layer) ---------- */
const NOTE = n => 440 * Math.pow(2, (n - 69) / 12);   // midi -> Hz

function bass(t, f, v = 0.5) {
  const o = S.ac.createOscillator(), o2 = S.ac.createOscillator(),
        g = S.ac.createGain(), lp = S.ac.createBiquadFilter();
  o.type = "sawtooth"; o.frequency.value = f;
  o2.type = "sine";    o2.frequency.value = f;
  lp.type = "lowpass"; lp.frequency.value = 240;
  g.gain.setValueAtTime(v * 0.5, t);
  g.gain.exponentialRampToValueAtTime(0.001, t + 0.4);
  o.connect(lp); o2.connect(lp);
  lp.connect(g).connect(S.ac.destination);
  o.start(t); o.stop(t + 0.45); o2.start(t); o2.stop(t + 0.45);
}

function stab(t, freqs, v = 0.28) {
  for (const f of freqs) {
    const o = S.ac.createOscillator(), o2 = S.ac.createOscillator(),
          g = S.ac.createGain(), lp = S.ac.createBiquadFilter();
    o.type = "sawtooth"; o.frequency.value = f;
    o2.type = "sawtooth"; o2.frequency.value = f * 1.007;   // detune
    lp.type = "lowpass"; lp.frequency.value = 1800;
    g.gain.setValueAtTime(v / freqs.length, t);
    g.gain.exponentialRampToValueAtTime(0.001, t + 0.22);
    o.connect(lp); o2.connect(lp);
    lp.connect(g).connect(S.ac.destination);
    o.start(t); o.stop(t + 0.25); o2.start(t); o2.stop(t + 0.25);
  }
}

function pad(t, freqs, dur = 3.2, v = 0.16) {
  for (const f of freqs) {
    const o = S.ac.createOscillator(), g = S.ac.createGain(),
          lp = S.ac.createBiquadFilter();
    o.type = "sawtooth"; o.frequency.value = f;
    lp.type = "lowpass"; lp.frequency.value = 900;
    g.gain.setValueAtTime(0.001, t);
    g.gain.linearRampToValueAtTime(v / freqs.length, t + 0.7);
    g.gain.setValueAtTime(v / freqs.length, t + dur - 0.6);
    g.gain.exponentialRampToValueAtTime(0.001, t + dur);
    o.connect(lp).connect(g).connect(S.ac.destination);
    o.start(t); o.stop(t + dur + 0.05);
  }
}

function lead(t, f0, v = 0.3, glideTo = 0, dur = 0.25) {
  const o = S.ac.createOscillator(), g = S.ac.createGain();
  o.type = "square";
  o.frequency.setValueAtTime(f0, t);
  if (glideTo) o.frequency.exponentialRampToValueAtTime(glideTo, t + 0.12);
  g.gain.setValueAtTime(v, t);
  g.gain.exponentialRampToValueAtTime(0.001, t + dur);
  o.connect(g).connect(S.ac.destination);
  o.start(t); o.stop(t + dur + 0.05);
}

/* electric guitar — saw through a waveshaper + lowpass; bend = pitch
   glide to a semitone target mid-note. hardrock/rockballad/polyphia
   get their character from riff+bend patterns, not this voice alone. */
let distCurve = null;
function guitar(t, f0, v = 0.4, bendSemis = 0, dur = 0.35) {
  if (!distCurve) {
    distCurve = new Float32Array(256);
    for (let i = 0; i < 256; i++)
      distCurve[i] = Math.tanh(3 * (i / 127.5 - 1));
  }
  const o = S.ac.createOscillator(), o2 = S.ac.createOscillator(),
        ws = S.ac.createWaveShaper(), lp = S.ac.createBiquadFilter(),
        g = S.ac.createGain();
  o.type = "sawtooth"; o.frequency.setValueAtTime(f0, t);
  o2.type = "sawtooth"; o2.frequency.setValueAtTime(f0 * 1.004, t);
  if (bendSemis) {
    const ft = f0 * Math.pow(2, bendSemis / 12);
    o.frequency.linearRampToValueAtTime(ft, t + 0.16);
    o2.frequency.linearRampToValueAtTime(ft * 1.004, t + 0.16);
  }
  ws.curve = distCurve;
  lp.type = "lowpass"; lp.frequency.value = 2600; lp.Q.value = 2.5;
  g.gain.setValueAtTime(v, t);
  g.gain.exponentialRampToValueAtTime(0.001, t + dur);
  o.connect(ws); o2.connect(ws);
  ws.connect(lp).connect(g).connect(S.ac.destination);
  o.start(t); o.stop(t + dur + 0.05); o2.start(t); o2.stop(t + dur + 0.05);
}

function clap(t, v = 0.5) {
  for (const dt of [0, 0.012, 0.024]) {
    const n = noiseSrc(t + dt, 0.03), bp = S.ac.createBiquadFilter(),
          g = S.ac.createGain();
    bp.type = "bandpass"; bp.frequency.value = 1200; bp.Q.value = 1.5;
    g.gain.setValueAtTime(v * 0.5, t + dt);
    g.gain.exponentialRampToValueAtTime(0.001, t + dt + 0.18);
    n.connect(bp).connect(g).connect(S.ac.destination);
  }
}
function ride(t, v = 0.2) {
  const n = noiseSrc(t, 0.3), bp = S.ac.createBiquadFilter(),
        g = S.ac.createGain();
  bp.type = "bandpass"; bp.frequency.value = 6800; bp.Q.value = 4;
  g.gain.setValueAtTime(v, t);
  g.gain.exponentialRampToValueAtTime(0.001, t + 0.35);
  n.connect(bp).connect(g).connect(S.ac.destination);
}
function tamb(t, v = 0.18) {
  const n = noiseSrc(t, 0.06), hp = S.ac.createBiquadFilter(),
        g = S.ac.createGain();
  hp.type = "highpass"; hp.frequency.value = 8000;
  g.gain.setValueAtTime(v, t);
  g.gain.exponentialRampToValueAtTime(0.001, t + 0.1);
  n.connect(hp).connect(g).connect(S.ac.destination);
}
function rim(t, v = 0.35) {
  const o = S.ac.createOscillator(), g = S.ac.createGain();
  o.type = "triangle"; o.frequency.value = 1740;
  g.gain.setValueAtTime(v, t);
  g.gain.exponentialRampToValueAtTime(0.001, t + 0.04);
  o.connect(g).connect(S.ac.destination);
  o.start(t); o.stop(t + 0.06);
}

/* ---------- music layer: styles + moods + instruments ---------- */
// control.json: {style, mood, instruments[], swing, bpm_offset}
const C = { style: "", mood: "", instruments: [], swing: 0, bpm_offset: 0 };

const SCALES = {
  blue:   [0,3,5,6,7,10],        // blues hexatonic — "blue chords"
  bright: [0,2,4,5,7,9,11],      // major
  tense:  [0,2,3,5,7,8,11],      // harmonic minor
  calm:   [0,2,4,6,7,9,11],      // lydian
};
const CHORD_SHAPE = {
  blue:   [0,3,7,10],            // min7 stabs
  bright: [0,4,7,11],            // maj7
  tense:  [0,3,6,10],            // m7b5 tension
  calm:   [0,4,7,11],            // maj7 pads
};
const ROOT = 45;   // A2 — blues-adjacent root, sits under the drum mix

// per-style drum grids + swing + bpm offset + riff (scale degrees, b=bend semis)
const STYLES = {
  rock: {
    kick:[1,0,0,0,1,0,0,0,1,0,0,0,1,0,0,0],
    snare:[0,0,0,0,1,0,0,0,0,0,0,0,1,0,0,0],
    hat:[1,0,1,0,1,0,1,0,1,0,1,0,1,0,1,0],
    tom:[0,0,0,0,0,0,0,0,0,0,0,0,0,0,1,0],
    crash:[1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
    swing:0, bpm:15,
    riff:[{s:0,d:0},{s:3,d:3,b:1},{s:6,d:0},{s:7,d:4},{s:10,d:5},{s:14,d:0}],
  },
  ballad: {
    kick:[1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
    snare:[0,0,0,0,0,0,0,0,0.7,0,0,0,0,0,0,0],
    hat:[1,0,0,0,0.6,0,0,0,0.8,0,0,0,0.6,0,0,0],
    ride:[0,0,1,0,0,0,1,0,0,0,1,0,0,0,1,0],
    swing:0, bpm:-15,
    riff:[{s:0,d:0,b:1},{s:8,d:4,b:1}],
  },
  funky: {
    kick:[1,0,0,0,0,0,0,1,0,0,1,0,0,0,0,0],
    snare:[0,0,0.3,0,1,0,0.3,0,0,0,0.3,0,1,0,0.4,0],
    hat:[1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,0],
    rim:[0,0,0,0,0,0,0,0,0,0,0,0,0,0,1,0],
    swing:0.12, bpm:0,
    riff:[{s:0,d:0},{s:3,d:6,b:1},{s:7,d:3},{s:10,d:6,b:1},{s:14,d:4}],
  },
  electronic: {
    kick:[1,0,0,0,1,0,0,0,1,0,0,0,1,0,0,0],
    clap:[0,0,0,0,1,0,0,0,0,0,0,0,1,0,0,0],
    hat:[0,0,1,0,0,0,1,0,0,0,1,0,0,0,1,0],
    shaker:[1,0,1,0,1,0,1,0,1,0,1,0,1,0,1,0],
    swing:0, bpm:10,
    riff:[{s:0,d:0},{s:4,d:0},{s:8,d:3},{s:12,d:4}],
  },
  edm: {
    kick:[1,0,0,0,1,0,0,0,1,0,0,0,1,0,0,0],
    clap:[0,0,0,0,1,0,0,0,0,0,0,0,1,0,0,0],
    hat:[0,0,1,0,0,0,1,0,0,0,1,0,0,0,1,1],
    crash:[1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
    tom:[0,0,0,0,0,0,0,0,0,0,0,0,0,0.5,0.6,0.8],
    swing:0, bpm:25,
    riff:[{s:0,d:0},{s:4,d:3},{s:8,d:4},{s:12,d:6}],
  },
  hardrock: {
    kick:[1,0,0,1,0,0,0,0,1,0,0,1,0,0,0,0],
    snare:[0,0,0,0,1,0,0,0,0,0,0,0,1,0,0,0],
    hat:[1,0,1,0,1,0,1,0,1,0,1,0,1,0,1,0],
    crash:[1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
    swing:0, bpm:20,
    riff:[{s:0,d:0},{s:1,d:0},{s:3,d:3,b:2},{s:6,d:0},{s:7,d:0},
          {s:10,d:5,b:1},{s:12,d:4},{s:14,d:0}],
  },
  rockballad: {
    kick:[1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
    snare:[0,0,0,0,0,0,0,0,0.7,0,0,0,0,0,0,0],
    ride:[1,0,0,0,1,0,0,0,1,0,0,0,1,0,0,0],
    crash:[1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
    swing:0, bpm:-10,
    riff:[{s:0,d:0,b:1},{s:6,d:4,b:2},{s:12,d:5,b:1}],
  },
  polyphia: {  // trap hats + staccato kick + harmonized virtuoso lead
    kick:[1,0,0,0,0,0,1,0,0,0,1,0,0,0,0,0],
    snare:[0,0,0,0,0,0,0,0,1,0,0,0,0,0,0,0],
    hat:[1,0,1,0,1,0,1,0,1,0,1,0,1,0,1,1],
    shaker:[0,0,0,0,0,0,0,1,0,0,0,0,0,0,0,1],  // trap rolls tail
    swing:0, bpm:5,
    riff:[{s:0,d:0},{s:2,d:6},{s:4,d:4,b:1},{s:6,d:6},{s:8,d:7},
          {s:10,d:9,b:2},{s:12,d:11},{s:14,d:6}],
    harmonize: true,
  },
};
const STAB_STEPS = { // chord stabs land on offbeats per style feel
  rock:[6,14], ballad:[], funky:[3,11], electronic:[2,10], edm:[2,6,10,14],
  hardrock:[], rockballad:[], polyphia:[7],
};
const VOICES2 = { bass, stab, pad, lead, guitar, clap, ride, tamb, rim };

function moodScale()  { return SCALES[C.mood] || SCALES.blue; }
function moodChord()  {
  const sh = CHORD_SHAPE[C.mood] || CHORD_SHAPE.blue;
  return sh.map(d => NOTE(ROOT + 12 + d));
}
function degToFreq(d, oct = 1) {
  const sc = moodScale(), o = Math.floor(d / sc.length);
  return NOTE(ROOT + 12 * (oct + o) + sc[d % sc.length]);
}

/* ---------- pattern engine ---------- */
const VOICE = { kick, snare, tom, hat, shaker };
// 16 steps per bar. state: healthy=1.0, degraded=0.4, error=accent 1.2
const PATTERN = {
  kick:   [1,0,0,0, 0,0,0,0, 1,0,0,0, 0,0,0,0],
  snare:  [0,0,0,0, 1,0,0,0, 0,0,0,0, 1,0,0,0],
  tom:    [0,0,0,0, 0,0,0,0, 0,0,0,0, 0,0,1,0],
  hat:    [1,0,1,0, 1,0,1,0, 1,0,1,0, 1,0,1,0],
  shaker: [0,1,0,1, 0,1,0,1, 0,1,0,1, 0,1,0,1],
};

function scheduleStep(step, t) {
  const hosts = (S.state && S.state.hosts) || {};
  const style = STYLES[C.style] || null;
  // swing: delay every odd 16th
  const sw = C.swing || (style ? style.swing : 0);
  if (sw && step % 2) t += (60 / S.bpm / 4) * sw;
  let crashed = false;
  for (const [host, h] of Object.entries(hosts)) {
    const row = (style && style[h.role]) || PATTERN[h.role];
    if (!row || !row[step]) continue;
    let v = { healthy: 1.0, quiet: 0.6, degraded: 0.35,
              error: 1.15, unknown: 0.5 }[h.state] ?? 0.6;
    v *= typeof row[step] === "number" && row[step] < 1 ? row[step] : 1;
    if (h.state === "error") {           // error = accent + stutter
      VOICE[h.role](t, v);
      VOICE[h.role](t + 0.03, v * 0.7);
      crashed = true;
      mark(host, "err");
      continue;
    }
    VOICE[h.role](t, v);
    mark(host, h.state === "degraded" ? "deg" : "hit");
  }
  // style voices without a host mapping (clap/ride/shaker extras)
  if (style) {
    for (const [name, row] of Object.entries(style)) {
      if (PATTERN[name] || typeof row !== "object") continue;
      if (row[step]) {
        const fn = VOICES2[name] || VOICE[name];
        if (fn) fn(t, 0.6 * (row[step] < 1 ? row[step] : 1));
      }
    }
  }
  // alerts = crash on bar 1
  if (step === 0 && S.state && (S.state.alerts || []).length && !crashed)
    crash(t, Math.min(0.4 + S.state.alerts.length * 0.08, 0.9));
  // ---- melodic layer (control.json) ----
  if (!style) return;
  const ins = C.instruments || [];
  if (ins.includes("bass") && ((style.kick && style.kick[step]) || step % 8 === 0))
    bass(t, NOTE(ROOT), 0.55);
  if (ins.includes("stab") && (STAB_STEPS[C.style] || []).includes(step))
    stab(t, moodChord(), 0.30);
  if (ins.includes("pad") && step === 0)
    pad(t, moodChord(), 60 / S.bpm * 4 * 0.95, 0.15);
  if (ins.includes("guitar") || ins.includes("lead")) {
    const fn = ins.includes("guitar") ? guitar : lead;
    for (const n of (style.riff || [])) {
      if (n.s !== step) continue;
      const f = degToFreq(n.d);
      fn(t, f, 0.42, n.b || 0, 0.34);
      if (style.harmonize)                      // polyphia double lead
        fn(t + 0.005, degToFreq(n.d + 2), 0.30, n.b || 0, 0.34);
    }
  }
  if (ins.includes("tamb") && step % 4 === 2) tamb(t);
}

function mark(host, cls) {
  const el = document.getElementById("h-" + host);
  if (!el) return;
  el.classList.add(cls);
  setTimeout(() => el.classList.remove("hit", "err", "deg"), 120);
}

/* ---------- scheduler (lookahead, drift-free) ---------- */
function tick() {
  const spb = 60 / S.bpm / 4;                  // 16th-note seconds
  while (S.next < S.ac.currentTime + LOOKAHEAD) {
    scheduleStep(S.step, S.next);
    S.next += spb;
    S.step = (S.step + 1) % 16;
  }
}

/* ---------- state feed ---------- */
async function fetchState() {
  try {
    const r = await fetch("state.json?ts=" + Date.now(), {cache: "no-store"});
    const st = await r.json();
    S.state = st;
    S.bpm = Math.min(Math.max(st.bpm || 72, 50), 140);
    render();
  } catch (e) { /* keep last state */ }
}
let urlOverride = false;
async function fetchControl() {
  try {
    // music control lives in the input-bridge (same origin, Caddy route)
    const r = await fetch("/api/input-bridge/percussion?ts=" + Date.now(),
                          {cache: "no-store"});
    const raw = await r.json();
    const c = raw.control || raw;
    if (!r.ok) return;
    if (urlOverride) {                       // URL params win over control.json
      if (!C.style && c.style) C.style = String(c.style);
      if (!C.mood && c.mood) C.mood = String(c.mood);
      if (!C.instruments.length && Array.isArray(c.instruments))
        C.instruments = c.instruments;
      const st = STYLES[C.style];
      if (st) S.bpm = Math.min(Math.max(
        (S.state && S.state.bpm || 72) + (st.bpm || 0), 50), 140);
      render();
      return;
    }
    C.style = String(c.style || "");
    C.mood = String(c.mood || "");
    C.instruments = Array.isArray(c.instruments) ? c.instruments : [];
    if (typeof c.swing === "number") C.swing = c.swing;
    if (typeof c.bpm_offset === "number") C.bpm_offset = c.bpm_offset;
    const st = STYLES[C.style];
    if (st) S.bpm = Math.min(Math.max(
      (S.state && S.state.bpm || 72) + (st.bpm || 0) + C.bpm_offset, 50), 140);
    render();
  } catch (e) { /* no control file — pure sonify mode */ }
}
function render() {
  const st = S.state; if (!st) return;
  const row = document.getElementById("row");
  const hosts = st.hosts || {};
  for (const [host, h] of Object.entries(hosts)) {
    if (!document.getElementById("h-" + host)) {
      const d = document.createElement("div");
      d.className = "host"; d.id = "h-" + host;
      d.innerHTML = `<div class="dot"></div>${host}<br>${h.role}`;
      row.appendChild(d);
    }
  }
  const a = (st.alerts || []);
  const music = C.style ? ` · ${C.style}${C.mood ? "+" + C.mood : ""}` +
    (C.instruments.length ? " [" + C.instruments.join(",") + "]" : "")
    : "";
  document.getElementById("stat").textContent =
    `bpm ${S.bpm} · ` +
    `${(st.summary && st.summary.reachable) ?? "?"}/` +
    `${(st.summary && st.summary.hosts) ?? "?"} up` +
    (typeof st.failing_services === "number"
      ? ` · ${st.failing_services} failing` : "") +
    (a.length ? ` · alerts: ${a.slice(0,3).join(", ")}` : "") + music;
  document.getElementById("log").textContent =
    a.length ? "watch: " + a.join(", ") : "";
}

/* ---------- boot ---------- */
function setRunning(on) {
  if (!S.ac) S.ac = new (window.AudioContext || window.webkitAudioContext)();
  S.ac.resume();
  S.on = on;
  const b = document.getElementById("go");
  if (S.on) {
    b.classList.add("on"); b.innerHTML = "■<br>live";
    S.step = 0; S.next = S.ac.currentTime + 0.1;
    S.timer = setInterval(tick, TICK_MS);
    fetchState(); setInterval(fetchState, 30000);
  } else {
    b.classList.remove("on"); b.innerHTML = "▶<br>listen";
    clearInterval(S.timer);
  }
}
document.getElementById("go").onclick = () => setRunning(!S.on);

// ?autostart — vcast casts this page as a live display foreground ("play
// percussion on screen N"): start without waiting for a tap. WebAudio
// still needs activation; if the AudioContext stays suspended the
// browser blocked it — the big button stays visible for a real tap.
if (new URLSearchParams(location.search).has("autostart")) {
  try {
    setRunning(true);
    if (S.ac && S.ac.state === "suspended") {
      // retry once the context unblocks (a tap anywhere on the page tree)
      const kick = () => { S.ac.resume(); };
      document.addEventListener("click", kick, { once: true });
      document.addEventListener("touchend", kick, { once: true });
    }
  } catch (e) { /* blocked — leave the listen button up */ }
}
fetchState(); setInterval(fetchState, 30000);   // passive preview state
fetchControl(); setInterval(fetchControl, 30000); // music layer (if configured)

// ?style=X&mood=Y&instruments=a,b — URL override for direct control
// (vcast can cast a styled session without touching control.json)
{
  const q = new URLSearchParams(location.search);
  if (q.get("style") && STYLES[q.get("style")]) { C.style = q.get("style"); urlOverride = true; }
  if (q.get("mood") && SCALES[q.get("mood")]) { C.mood = q.get("mood"); urlOverride = true; }
  const ins = q.get("instruments");
  if (ins) { C.instruments = ins.split(",").filter(i => i in VOICES2); urlOverride = true; }
}
