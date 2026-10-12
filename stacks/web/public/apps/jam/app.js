/* Ada Net Jam — 100% client-side music toy (card jam-session-app).
   WebAudio synth engine ported from Nest Percussion; input comes from
   YOU (pads / camera landmarks / mic), not the fleet — state.json is an
   optional module.

   Module contract: JAM.register(name, {init, onEvent, destroy}).
   Event bus: JAM.emit(evt, val) -> bindings[evt] -> instruments/fx.
   Bindings are user-editable and ride the URL hash (#cfg=base64) so a
   tuned setup is shareable by link. */
"use strict";

/* ---------- audio core ---------- */
const S = { ac: null, noise: null, fxIn: null, fx: {} };
function actx() {
  if (!S.ac) {
    S.ac = new (window.AudioContext || window.webkitAudioContext)();
    S.fxIn = S.ac.createGain();
    S.fxIn.connect(S.ac.destination);
  }
  if (S.ac.state === "suspended") S.ac.resume();
  return S.ac;
}
// chrome autoplay policy: a fresh page is muted until a REAL touch —
// resume on any tap anywhere, and show a banner while still locked
document.addEventListener("pointerdown", () => {
  if (S.ac && S.ac.state === "suspended") S.ac.resume();
});
const _muteEl = document.createElement("div");
_muteEl.id = "mute-banner";
_muteEl.textContent = "🔇 tap screen to unmute";
Object.assign(_muteEl.style, {
  position: "fixed", inset: "0", display: "none",
  alignItems: "center", justifyContent: "center",
  fontSize: "8vw", fontWeight: "700", color: "#fff",
  background: "rgba(0,0,0,.72)", zIndex: "99", cursor: "pointer",
});
document.body.appendChild(_muteEl);
setInterval(() => {
  _muteEl.style.display =
    (S.ac && S.ac.state === "suspended") ? "flex" : "none";
}, 500);
// diag overlay: top event emitters — when it "screams", the HUD names it
const _diag = document.createElement("div");
_diag.style.cssText = "position:fixed;top:6px;left:50%;transform:translateX(-50%);z-index:98;" +
  "font:11px ui-monospace,monospace;color:#4ade80;opacity:.75;white-space:pre";
document.body.appendChild(_diag);
setInterval(() => {
  const top = Object.entries(JAM._ec || {}).sort((a, b) => b[1] - a[1]).slice(0, 5);
  _diag.textContent = top.map(([k, n]) => `${k}×${n}`).join("  ");
}, 1000);
function noiseSrc(t, dur) {
  if (!S.noise) {
    const b = actx().createBuffer(1, S.ac.sampleRate * 1.2, S.ac.sampleRate);
    const d = b.getChannelData(0);
    for (let i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1;
    S.noise = b;
  }
  const s = actx().createBufferSource();
  s.buffer = S.noise; s.start(t); s.stop(t + dur + 0.05);
  return s;
}
const NOTE = n => 440 * Math.pow(2, (n - 69) / 12);

/* ---------- instrument voices (from Nest Percussion) ---------- */
function kick(t, v = 1) {
  const o = actx().createOscillator(), g = actx().createGain();
  o.frequency.setValueAtTime(150, t);
  o.frequency.exponentialRampToValueAtTime(38, t + 0.11);
  g.gain.setValueAtTime(v, t);
  g.gain.exponentialRampToValueAtTime(0.001, t + 0.35);
  o.connect(g).connect(S.fxIn); o.start(t); o.stop(t + 0.4);
}
function snare(t, v = 1) {
  const n = noiseSrc(t, 0.18), bp = actx().createBiquadFilter(),
        g = actx().createGain();
  bp.type = "bandpass"; bp.frequency.value = 1800; bp.Q.value = 0.9;
  g.gain.setValueAtTime(0.7 * v, t);
  g.gain.exponentialRampToValueAtTime(0.001, t + 0.16);
  n.connect(bp).connect(g).connect(S.fxIn);
  const o = actx().createOscillator(), g2 = actx().createGain();
  o.frequency.value = 185;
  g2.gain.setValueAtTime(0.35 * v, t);
  g2.gain.exponentialRampToValueAtTime(0.001, t + 0.1);
  o.connect(g2).connect(S.fxIn); o.start(t); o.stop(t + 0.12);
}
function tom(t, v = 1) {
  const o = actx().createOscillator(), g = actx().createGain();
  o.frequency.setValueAtTime(220, t);
  o.frequency.exponentialRampToValueAtTime(95, t + 0.12);
  g.gain.setValueAtTime(0.6 * v, t);
  g.gain.exponentialRampToValueAtTime(0.001, t + 0.25);
  o.connect(g).connect(S.fxIn); o.start(t); o.stop(t + 0.3);
}
function hat(t, v = 1, open = false) {
  const n = noiseSrc(t, 0.05), hp = actx().createBiquadFilter(),
        g = actx().createGain();
  hp.type = "highpass"; hp.frequency.value = 7000;
  g.gain.setValueAtTime(0.32 * v, t);
  g.gain.exponentialRampToValueAtTime(0.001, t + (open ? 0.25 : 0.04));
  n.connect(hp).connect(g).connect(S.fxIn);
}
function clap(t, v = 0.5) {
  for (const dt of [0, 0.012, 0.024]) {
    const n = noiseSrc(t + dt, 0.03), bp = actx().createBiquadFilter(),
          g = actx().createGain();
    bp.type = "bandpass"; bp.frequency.value = 1200; bp.Q.value = 1.5;
    g.gain.setValueAtTime(v * 0.5, t + dt);
    g.gain.exponentialRampToValueAtTime(0.001, t + dt + 0.18);
    n.connect(bp).connect(g).connect(S.fxIn);
  }
}
function crash(t, v = 0.8) {
  const n = noiseSrc(t, 1.2), hp = actx().createBiquadFilter(),
        g = actx().createGain();
  hp.type = "highpass"; hp.frequency.value = 4000;
  g.gain.setValueAtTime(v, t);
  g.gain.exponentialRampToValueAtTime(0.001, t + 1.0);
  n.connect(hp).connect(g).connect(S.fxIn);
}
function rim(t, v = 0.35) {
  const o = actx().createOscillator(), g = actx().createGain();
  o.type = "triangle"; o.frequency.value = 1740;
  g.gain.setValueAtTime(v, t);
  g.gain.exponentialRampToValueAtTime(0.001, t + 0.04);
  o.connect(g).connect(S.fxIn); o.start(t); o.stop(t + 0.06);
}
function shaker(t, v = 1) {
  const n = noiseSrc(t, 0.05), bp = actx().createBiquadFilter(),
        g = actx().createGain();
  bp.type = "bandpass"; bp.frequency.value = 5200; bp.Q.value = 3;
  g.gain.setValueAtTime(0.25 * v, t);
  g.gain.exponentialRampToValueAtTime(0.001, t + 0.06);
  n.connect(bp).connect(g).connect(S.fxIn);
}
let distCurve = null;
function guitar(t, f0, v = 0.4, bendSemis = 0, dur = 0.35) {
  if (!distCurve) {
    distCurve = new Float32Array(256);
    for (let i = 0; i < 256; i++)
      distCurve[i] = Math.tanh(3 * (i / 127.5 - 1));
  }
  const o = actx().createOscillator(), o2 = actx().createOscillator(),
        ws = actx().createWaveShaper(), lp = actx().createBiquadFilter(),
        g = actx().createGain();
  o.type = "sawtooth"; o.frequency.value = f0; o2.frequency.value = f0 * 1.004;
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
  ws.connect(lp).connect(g).connect(S.fxIn);
  o.start(t); o.stop(t + dur + 0.05); o2.start(t); o2.stop(t + dur + 0.05);
}
function lead(t, f0, v = 0.3, glideTo = 0, dur = 0.25) {
  const o = actx().createOscillator(), g = actx().createGain();
  o.type = "square";
  o.frequency.setValueAtTime(f0, t);
  if (glideTo) o.frequency.exponentialRampToValueAtTime(glideTo, t + 0.12);
  g.gain.setValueAtTime(v, t);
  g.gain.exponentialRampToValueAtTime(0.001, t + dur);
  o.connect(g).connect(S.fxIn); o.start(t); o.stop(t + dur + 0.05);
}
function bass(t, f, v = 0.5) {
  const o = actx().createOscillator(), o2 = actx().createOscillator(),
        g = actx().createGain(), lp = actx().createBiquadFilter();
  o.type = "sawtooth"; o.frequency.value = f;
  o2.type = "sine"; o2.frequency.value = f;
  lp.type = "lowpass"; lp.frequency.value = 240;
  g.gain.setValueAtTime(v * 0.5, t);
  g.gain.exponentialRampToValueAtTime(0.001, t + 0.4);
  o.connect(lp); o2.connect(lp); lp.connect(g).connect(S.fxIn);
  o.start(t); o.stop(t + 0.45); o2.start(t); o2.stop(t + 0.45);
}
function stab(t, freqs, v = 0.28) {
  for (const f of freqs) {
    const o = actx().createOscillator(), o2 = actx().createOscillator(),
          g = actx().createGain(), lp = actx().createBiquadFilter();
    o.type = "sawtooth"; o.frequency.value = f;
    o2.type = "sawtooth"; o2.frequency.value = f * 1.007;
    lp.type = "lowpass"; lp.frequency.value = 1800;
    g.gain.setValueAtTime(v / freqs.length, t);
    g.gain.exponentialRampToValueAtTime(0.001, t + 0.22);
    o.connect(lp); o2.connect(lp);
    lp.connect(g).connect(S.fxIn);
    o.start(t); o.stop(t + 0.25); o2.start(t); o2.stop(t + 0.25);
  }
}
/* fun one-shots */
function airhorn(t, v = 0.5) {
  for (const f of [466, 466, 622]) {
    const o = actx().createOscillator(), g = actx().createGain(),
          lp = actx().createBiquadFilter();
    o.type = "sawtooth"; o.frequency.value = f;
    lp.type = "lowpass"; lp.frequency.value = 2000;
    g.gain.setValueAtTime(v / 3, t);
    g.gain.exponentialRampToValueAtTime(0.001, t + 0.5);
    o.connect(lp).connect(g).connect(S.fxIn);
    o.start(t); o.stop(t + 0.55);
  }
}
function riser(t, v = 0.25) {
  const n = noiseSrc(t, 1.6), bp = actx().createBiquadFilter(),
        g = actx().createGain();
  bp.type = "bandpass"; bp.Q.value = 1.2;
  bp.frequency.setValueAtTime(400, t);
  bp.frequency.exponentialRampToValueAtTime(6000, t + 1.5);
  g.gain.setValueAtTime(0.001, t);
  g.gain.exponentialRampToValueAtTime(v, t + 1.4);
  g.gain.exponentialRampToValueAtTime(0.001, t + 1.6);
  n.connect(bp).connect(g).connect(S.fxIn);
}
function scratch(t, v = 0.4) {
  const o = actx().createOscillator(), g = actx().createGain();
  o.type = "sawtooth";
  o.frequency.setValueAtTime(700, t);
  o.frequency.linearRampToValueAtTime(300, t + 0.12);
  o.frequency.linearRampToValueAtTime(900, t + 0.24);
  g.gain.setValueAtTime(v, t);
  g.gain.exponentialRampToValueAtTime(0.001, t + 0.3);
  o.connect(g).connect(S.fxIn); o.start(t); o.stop(t + 0.32);
}

/* --- less-synthy timbres --- */
function pluck(t, f, v = 0.5) {          // Karplus-Strong string
  const ac = actx(), n = noiseSrc(t, 0.008);
  const dly = ac.createDelay(0.05), fb = ac.createGain(),
        lp = ac.createBiquadFilter(), g = ac.createGain();
  dly.delayTime.value = 1 / f;
  fb.gain.value = 0.93;
  lp.type = "lowpass"; lp.frequency.value = 1500;
  g.gain.value = v * 0.7;
  n.connect(dly); dly.connect(lp); lp.connect(fb); fb.connect(dly);
  dly.connect(g).connect(S.fxIn);
  fb.gain.setTargetAtTime(0, t + 1.0, 0.2);
  setTimeout(() => { try { fb.disconnect(); } catch {} }, 3500);
}
function bell(t, f, v = 0.3, dur = 0.9) {  // soft FM marimba (small index,
  const ac = actx(), c = ac.createOscillator(), m = ac.createOscillator(),  // fast decay)
        mg = ac.createGain(), g = ac.createGain(), lp = ac.createBiquadFilter();
  c.frequency.value = f; m.frequency.value = f * 3;
  mg.gain.setValueAtTime(f * 0.6, t);
  mg.gain.exponentialRampToValueAtTime(1, t + 0.12);
  m.connect(mg); mg.connect(c.frequency);
  lp.type = "lowpass"; lp.frequency.value = 2800;
  g.gain.setValueAtTime(v, t);
  g.gain.exponentialRampToValueAtTime(0.001, t + dur);
  c.connect(lp); lp.connect(g).connect(S.fxIn);
  c.start(t); c.stop(t + dur + 0.05); m.start(t); m.stop(t + 0.2);
}
function organ(t, f, v = 0.3, dur = 0.5) { // drawbar organ tone
  const ac = actx(), g = ac.createGain(), lp = ac.createBiquadFilter();
  lp.type = "lowpass"; lp.frequency.value = 4000;
  g.gain.setValueAtTime(v * 0.32, t);
  g.gain.setTargetAtTime(0, t + dur - 0.15, 0.05);
  for (const [r, a] of [[1, 1], [2, 0.6], [3, 0.4], [4, 0.25]]) {
    const o = ac.createOscillator(), og = ac.createGain();
    o.type = "sine"; o.frequency.value = f * r; og.gain.value = a;
    o.connect(og).connect(g); o.start(t); o.stop(t + dur + 0.1);
  }
  g.connect(lp).connect(S.fxIn);
}

/* gliding pad voice — one sustained theremin tone per key. Pitch moves
   via setTargetAtTime so hand motion GLIDES, never trills. Modules fade
   it in on hand-presence and call toneDrop on teardown. */
const TONES = {};
function tone(key, type) {
  if (!TONES[key]) {
    const ac = actx(), o = ac.createOscillator(), g = ac.createGain(),
          lp = ac.createBiquadFilter();
    o.type = type || "sine"; g.gain.value = 0;
    lp.type = "lowpass"; lp.frequency.value = 1600; lp.Q.value = 0.4;
    o.connect(g); g.connect(lp); lp.connect(ac.destination); o.start();
    TONES[key] = { o, g };
  }
  return TONES[key];
}
function toneDrop(key) {
  const v = TONES[key]; if (!v) return;
  delete TONES[key];
  try { v.g.gain.setTargetAtTime(0, actx().currentTime, 0.05); } catch {}
  setTimeout(() => { try { v.o.stop(); } catch {} }, 400);
}

/* ---------- JAM core: registry + bus + bindings ---------- */
const EVENTS = [
  "pad-kick","pad-snare","pad-hat","pad-tom","pad-clap","pad-crash",
  "pad-rim","pad-shaker",
  "hand-strike-L","hand-strike-R","hand-move-L","hand-move-R",
  "clap","hum-note","nod","smile","shake","mouth","brow",
  "lean","jump","arm-up-L","arm-up-R","swipe-L","swipe-R",
];
const TARGETS = [
  "kick","snare","hat","tom","clap","crash","rim","shaker",
  "bass-note","lead-note","chord-stab","pluck-note","bell-note","organ-stab",
  "airhorn","riser","scratch",
];
const DEFAULT_BINDINGS = {
  "hand-strike-L": "kick", "hand-strike-R": "snare",
  "clap": "clap", "hum-note": "lead-note",
  "nod": "crash", "smile": "chord-stab",
  "shake": "scratch", "mouth": "airhorn", "jump": "riser",
  "arm-up-L": "rim", "arm-up-R": "shaker",
};
const SCALES = { blue: [0,3,5,6,7,10], bright: [0,2,4,5,7,9,11],
                 tense: [0,2,3,5,7,8,11], calm: [0,2,4,6,7,9,11] };

const JAM = {
  mods: {},
  bindings: {},
  hud: m => { document.getElementById("hud").textContent = m; },

  register(name, mod) {
    this.mods[name] = { ...mod, enabled: false, handle: null };
    const b = document.createElement("button");
    b.className = "btn"; b.textContent = name;
    b.onclick = () => this.toggle(name, b);
    document.getElementById("mods").appendChild(b);
  },

  toggle(name, btn) {
    const m = this.mods[name]; if (!m) return;
    m.enabled = !m.enabled;
    if (btn) btn.classList.toggle("on", m.enabled);
    if (m.enabled) {
      Promise.resolve(m.init(this)).catch(e => {
        m.enabled = false; if (btn) btn.classList.remove("on");
        this.hud(`${name} unavailable: ${e.message || e}`);
      });
    } else if (m.destroy) m.destroy();
  },

  emit(evt, val) {
    (this._ec ||= {})[evt] = (this._ec[evt] || 0) + 1;   // diag: who fires
    const tgt = this.bindings[evt];
    if (tgt) this.hit(tgt, val);
    for (const [n, m] of Object.entries(this.mods))
      if (m.enabled && m.onEvent) try { m.onEvent(evt, val); } catch {}
  },

  hit(tgt, val = 1) {
    const t = actx().currentTime;
    const scale = SCALES.blue, root = 45;
    switch (tgt) {
      case "kick": kick(t, val); break;
      case "snare": snare(t, val); break;
      case "hat": hat(t, val); break;
      case "tom": tom(t, val); break;
      case "clap": clap(t, val); break;
      case "crash": crash(t, val); break;
      case "rim": rim(t, val); break;
      case "shaker": shaker(t, val); break;
      case "airhorn": airhorn(t, val); break;
      case "riser": riser(t, val); break;
      case "scratch": scratch(t, val); break;
      case "bass-note": bass(t, NOTE(root + scale[(val * 7 | 0) % scale.length])); break;
      case "lead-note": lead(t, NOTE(root + 12 + scale[(val * 7 | 0) % scale.length]), 0.3, 0, 0.4); break;
      case "chord-stab": stab(t, [0,3,7,10].map(s => NOTE(root + 12 + s))); break;
      case "pluck-note": pluck(t, NOTE(root + 12 + scale[(val * 7 | 0) % scale.length]), 0.55); break;
      case "bell-note": bell(t, NOTE(root + 24 + scale[(val * 7 | 0) % scale.length]), 0.3); break;
      case "organ-stab": [0,3,7].forEach(s => organ(t, NOTE(root + 12 + s), 0.3)); break;
      case "fx-delay": case "fx-verb": case "fx-crush": case "fx-stutter":
        if (JAM.mods.fx?.enabled) JAM.mods.fx.toggleFx(tgt);
        break;
    }
  },

  loadBindings() {
    const h = location.hash.match(/#cfg=([A-Za-z0-9_-]+)/);
    if (h) {
      try {
        this.bindings = JSON.parse(
          decodeURIComponent(escape(atob(h[1].replace(/-/g, "+").replace(/_/g, "/")))));
      } catch { this.bindings = { ...DEFAULT_BINDINGS }; }
    } else this.bindings = { ...DEFAULT_BINDINGS };
  },
  shareURL() {
    const cfg = btoa(unescape(encodeURIComponent(JSON.stringify(this.bindings))))
      .replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
    return location.origin + location.pathname + "#cfg=" + cfg;
  },
};
window.JAM = JAM;
// voices + helpers exposed for mods (band schedules these on its own clock)
JAM._v = { kick, snare, hat, tom, clap, crash, rim, shaker,
           bass, lead, stab, airhorn, riser, scratch, pluck, bell, organ };
// diag: count every VOICE call too — band/fills bypass emit entirely, so
// a runaway scheduler was invisible to the event counter
for (const [k, f] of Object.entries(JAM._v))
  JAM._v[k] = (...a) => {
    (JAM._ec ||= {})["♪" + k] = (JAM._ec["♪" + k] || 0) + 1;
    return f(...a);
  };
JAM._actx = actx; JAM._NOTE = NOTE; JAM._SCALES = SCALES;
JAM._tone = tone; JAM._toneDrop = toneDrop;
// ?tones=0 kills all glide voices — A/B flag for "is the theremin the scream?"
JAM.tonesOff = new URLSearchParams(location.search).get("tones") === "0";
JAM.loadBindings();

/* ---------- pad grid (always on) ---------- */
const PADS = [
  ["pad-kick","🥁","kick"],["pad-snare","🥁","snare"],["pad-hat","🎩","hat"],["pad-tom","🪘","tom"],
  ["pad-clap","👏","clap"],["pad-crash","💥","crash"],["pad-rim","🥢","rim"],["pad-shaker","🪇","shaker"],
];
const padEl = {};
for (const [evt, ic, label] of PADS) {
  const d = document.createElement("div");
  d.className = "pad"; d.innerHTML = `<span class="ic">${ic}</span>${label}`;
  d.onpointerdown = () => {
    JAM.emit(evt, 1);
    d.classList.add("hit"); setTimeout(() => d.classList.remove("hit"), 120);
    JAM.bindings[evt] = JAM.bindings[evt] || label;
  };
  padEl[evt] = d;
  document.getElementById("pads").appendChild(d);
  // pads are also real events: default-bind them
  if (!JAM.bindings[evt]) JAM.bindings[evt] = label;
}

/* ---------- FX row ---------- */
const FX = [["fx-delay","⏱ delay"],["fx-verb","🌊 verb"],["fx-crush","📻 crush"],["fx-stutter","⏸ stutter"],
            ["fun-airhorn","📯 airhorn"],["fun-riser","🚀 riser"],["fun-scratch","💿 scratch"]];
for (const [id, label] of FX) {
  const b = document.createElement("button");
  b.className = "btn"; b.id = "b-" + id; b.textContent = label;
  b.onclick = () => {
    if (id.startsWith("fun-")) JAM.hit(id.slice(4));
    else if (JAM.mods.fx?.enabled) JAM.mods.fx.toggleFx(id, b);
    else JAM.hud("enable the fx module first");
  };
  document.getElementById("fx").appendChild(b);
}

/* ---------- bindings matrix UI ---------- */
function drawMatrix() {
  const wrap = document.getElementById("matrix-wrap");
  let h = "<table id='matrix'><tr><th>event \\ sound</th>" +
    TARGETS.map(t => `<th>${t}</th>`).join("") + "</tr>";
  for (const e of EVENTS) {
    h += `<tr><th>${e}</th>` + TARGETS.map(t =>
      `<td class="${JAM.bindings[e] === t ? "on" : ""}" data-e="${e}" data-t="${t}"></td>`).join("") + "</tr>";
  }
  wrap.innerHTML = h + "</table>";
  wrap.querySelectorAll("td").forEach(td => td.onclick = () => {
    const e = td.dataset.e;
    if (JAM.bindings[e] === td.dataset.t) delete JAM.bindings[e];
    else JAM.bindings[e] = td.dataset.t;
    drawMatrix();
  });
}
drawMatrix();

/* ---------- top bar ---------- */
document.getElementById("b-cam").onclick = e => JAM.toggle("hands", e.target);
document.getElementById("b-mic").onclick = e => JAM.toggle("mic", e.target);
document.getElementById("b-share").onclick = async () => {
  const u = JAM.shareURL();
  try { await navigator.clipboard.writeText(u); JAM.hud("setup link copied — " + u); }
  catch { JAM.hud(u); }
};
document.getElementById("b-fb").onclick = () => {
  const msg = encodeURIComponent(
    "Jam Session feedback 🎵 (tried " + location.origin + location.pathname + "):\n");
  window.open("https://line.me/R/share?text=" + msg, "_blank");
};

/* ---------- acts ---------- */
// raw      = direct move -> instrument (all input mods, no backing)
// autotune = backing band + remote; the app adapts to you
const ACTS = { raw: [], autotune: ["remote", "band"] };
for (const [act, mods] of Object.entries(ACTS)) {
  const b = document.createElement("button");
  b.className = "btn"; b.textContent = act === "raw" ? "🎭 raw act" : "🎹 auto tune";
  b.onclick = () => {
    if (act === "raw") {
      if (JAM.mods.band?.enabled) JAM.toggle("band");
      JAM.hud("🎭 raw act — your moves drive the instruments directly");
    } else {
      for (const m of mods)
        if (JAM.mods[m] && !JAM.mods[m].enabled)
          JAM.toggle(m, [...document.querySelectorAll("#mods .btn")]
            .find(x => x.textContent === m));
    }
  };
  document.getElementById("mods").appendChild(b);
}

/* ---------- module loader ---------- */
// ?mods=remote,fx auto-enables modules once their script registers
const wantMods = new Set(
  (new URLSearchParams(location.search).get("mods") || "").split(",").filter(Boolean));
for (const m of ["fx", "hands", "mic", "remote", "band"]) {
  const s = document.createElement("script");
  s.src = "mod/" + m + ".js?v=" +
    (new URLSearchParams(location.search).get("v") || Date.now());
  s.onload = () => {
    if (wantMods.has(m)) {
      const btn = [...document.querySelectorAll("#mods .btn")]
        .find(b => b.textContent === m);
      JAM.toggle(m, btn);
    }
  };
  s.onerror = () => {};   // optional module missing = fine
  document.body.appendChild(s);
}
