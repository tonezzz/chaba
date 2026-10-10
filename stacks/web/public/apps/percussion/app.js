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
  let crashed = false;
  for (const [host, h] of Object.entries(hosts)) {
    const row = PATTERN[h.role];
    if (!row || !row[step]) continue;
    let v = { healthy: 1.0, quiet: 0.6, degraded: 0.35,
              error: 1.15, unknown: 0.5 }[h.state] ?? 0.6;
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
  // alerts = crash on bar 1
  if (step === 0 && S.state && (S.state.alerts || []).length && !crashed)
    crash(t, Math.min(0.4 + S.state.alerts.length * 0.08, 0.9));
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
  document.getElementById("stat").textContent =
    `bpm ${S.bpm} · ${st.events_per_hour ?? "?"} ev/h · ` +
    `${(st.summary && st.summary.healthy) ?? "?"}/` +
    `${(st.summary && st.summary.total) ?? "?"} green` +
    (a.length ? ` · alerts: ${a.slice(0,3).join(", ")}` : "");
  document.getElementById("log").textContent =
    a.length ? "watch: " + a.join(", ") : "";
}

/* ---------- boot ---------- */
document.getElementById("go").onclick = () => {
  if (!S.ac) S.ac = new (window.AudioContext || window.webkitAudioContext)();
  S.ac.resume();
  S.on = !S.on;
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
};
fetchState(); setInterval(fetchState, 30000);   // passive preview state
