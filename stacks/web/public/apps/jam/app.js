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

/* ---------- JAM core: registry + bus + bindings ---------- */
const EVENTS = [
  "pad-kick","pad-snare","pad-hat","pad-tom","pad-clap","pad-crash",
  "pad-rim","pad-shaker",
  "hand-strike-L","hand-strike-R","hand-move-L","hand-move-R",
  "clap","hum-note","nod","smile",
];
const TARGETS = [
  "kick","snare","hat","tom","clap","crash","rim","shaker",
  "bass-note","lead-note","chord-stab","airhorn","riser","scratch",
];
const DEFAULT_BINDINGS = {
  "hand-strike-L": "kick", "hand-strike-R": "snare",
  "hand-move-L": "lead-note", "hand-move-R": "bass-note",
  "clap": "clap", "hum-note": "lead-note",
  "nod": "crash", "smile": "chord-stab",
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

/* ---------- module loader ---------- */
for (const m of ["fx", "hands", "mic", "remote"]) {
  const s = document.createElement("script");
  s.src = "mod/" + m + ".js";
  s.onerror = () => {};   // optional module missing = fine
  document.body.appendChild(s);
}
