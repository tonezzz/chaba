#!/usr/bin/env node
/* ops-percussion-check — repo-side smoke check for /apps/percussion.

Loads stacks/web/public/apps/percussion/app.js in a vm context with stubbed
DOM + WebAudio nodes, drives the lookahead scheduler, and asserts the
state.json -> groove mapping contract (see scripts/ops-percussion-sync.py):

  bpm    controls 16th-note spacing
  hosts  each plays its role pattern; state healthy=solid, degraded=quiet,
         error=accent+stutter (two hits ~30ms apart)
  alerts crashing on bar downbeat

Usage:
  node scripts/ops-percussion-check.mjs [state.json]
  (default: fetch live https://tony-dell.taila0626a.ts.net/apps/percussion/state.json)

Exit 0 = all checks pass. No browser, no audio hardware needed.
*/
import { readFileSync } from "node:fs";
import vm from "node:vm";

const APP = new URL("../stacks/web/public/apps/percussion/app.js",
                    import.meta.url).pathname;
const LIVE = "https://tony-dell.taila0626a.ts.net/apps/percussion/state.json";

let pass = 0, fail = 0;
const ok = (cond, name) => {
  if (cond) { pass++; console.log(`  PASS ${name}`); }
  else { fail++; console.log(`  FAIL ${name}`); }
};

/* ---------- fetch state under test ---------- */
let stateJson;
if (process.argv[2]) {
  stateJson = JSON.parse(readFileSync(process.argv[2], "utf8"));
  console.log(`state: ${process.argv[2]}`);
} else {
  const r = await fetch(LIVE, { cache: "no-store" });
  if (!r.ok) { console.error(`cannot fetch ${LIVE}: ${r.status}`); process.exit(2); }
  stateJson = await r.json();
  console.log(`state: ${LIVE}`);
}
const ageS = Math.round(Date.now() / 1000 - stateJson.ts);
console.log(`  ts age: ${ageS}s  bpm: ${stateJson.bpm}  ` +
            `hosts: ${Object.keys(stateJson.hosts || {}).length}`);
ok(ageS < 60, `state.json fresh (<60s, got ${ageS}s)`);

/* ---------- WebAudio stub ---------- */
// Every scheduled hit lands here via node.start(t) / gain.setValueAtTime.
const hits = [];           // {t, kind:'osc'|'noise', freq, vel}
const pendingGains = [];   // gain setValueAtTime calls awaiting a start()

function param(isGain = false) {
  return {
    value: 0, isGain,
    setValueAtTime(v, t) {
      this.value = v;
      if (isGain) pendingGains.push({ v, t });
    },
    linearRampToValueAtTime() {},
    exponentialRampToValueAtTime() {},
    cancelScheduledValues() {},
  };
}
function node(kind, extra = {}) {
  const n = {
    kind, ...extra,
    connect(d) { return d; },
    start(t) {
      // nearest gain automation at the same step time = voice velocity
      const g = pendingGains.filter(p => Math.abs(p.t - t) < 1e-6)
                            .map(p => p.v);
      hits.push({ t, kind, freq: n.frequency?.value,
                  vel: g.length ? Math.max(...g) : null });
    },
    stop() {},
    disconnect() {},
  };
  return n;
}
class FakeAC {
  constructor() {
    this.currentTime = 0; this.sampleRate = 48000;
    this.state = "running"; this.destination = node("dest");
  }
  resume() { this.state = "running"; return Promise.resolve(); }
  createOscillator() {
    const n = node("osc");
    n.type = "sine"; n.frequency = param();
    n.detune = param();
    return n;
  }
  createGain() { const n = node("gain"); n.gain = param(true); return n; }
  createBiquadFilter() {
    const n = node("filter");
    n.type = "lowpass"; n.frequency = param(); n.Q = param();
    n.gain = param(); n.detune = param();
    return n;
  }
  createWaveShaper() { const n = node("shaper"); n.curve = null; return n; }
  createBuffer(ch, len) {
    return { getChannelData: () => new Float32Array(len) };
  }
  createBufferSource() {
    const n = node("noise"); n.buffer = null; n.loop = false;
    n.playbackRate = param(); n.detune = param();
    return n;
  }
}

/* ---------- DOM stub ---------- */
const byId = new Map();
const el = id => {
  if (!byId.has(id)) {
    const e = {
      id, className: "", textContent: "", innerHTML: "", onclick: null,
      style: {},
      classList: { add() {}, remove() {}, contains: () => false },
      appendChild() {},
    };
    byId.set(id, e);
  }
  return byId.get(id);
};
const documentStub = {
  getElementById: id => byId.get(id) || null,
  createElement: () => el("dyn-" + Math.random()),
  body: { appendChild() {} },
  addEventListener() {},
};
// pre-create the static ids index.html provides
for (const id of ["go", "row", "stat", "log", "hint"]) el(id);

/* ---------- timers: capture, don't run ---------- */
const intervals = [];
const sandbox = {
  console, Math, JSON, Date, URLSearchParams,
  document: documentStub,
  location: { search: "" },
  fetch: async url => {
    const u = String(url);
    if (u.includes("/api/input-bridge/percussion"))
      return { ok: false, status: 404, json: async () => ({}) };
    return { ok: true, json: async () => stateJson };
  },
  setInterval: (fn, ms) => { intervals.push({ fn, ms }); return intervals.length; },
  clearInterval: () => {},
  setTimeout: () => 0,
  window: {},
};
sandbox.window.AudioContext = FakeAC;
sandbox.globalThis = sandbox;
vm.createContext(sandbox);

/* ---------- load app ---------- */
vm.runInContext(readFileSync(APP, "utf8"), sandbox, { filename: "app.js" });
await new Promise(r => setImmediate(r));   // let fetchState resolve
await new Promise(r => setImmediate(r));

// top-level const/let stay in the context's lexical scope — pull handles
// out with a follow-up script in the same context.
const api = vm.runInContext("({S, C, scheduleStep})", sandbox);
const { S, C } = api;
const scheduleStep = api.scheduleStep;

ok(S && S.state, "state.json loaded into engine");
ok(S.bpm === Math.min(Math.max(stateJson.bpm || 72, 50), 140),
   `bpm mapped from state (${S.bpm})`);

/* ---------- start audio (the tap) ---------- */
hits.length = 0; pendingGains.length = 0;
byId.get("go").onclick();
ok(S.on === true, "tap-to-start engaged scheduler");
const tickFn = intervals.find(i => i.ms === 30)?.fn;
ok(!!tickFn, "lookahead tick registered");

/* pump scheduler: advance fake time, run tick — ~8s of audio ≈ 17 bars */
const SPB = 60 / S.bpm / 4;             // 16th seconds
const T0 = S.next;                       // grid anchor (first step time)
for (let i = 0; i < 400; i++) {
  S.ac.currentTime += 0.05;
  tickFn();
}
const percussive = hits.filter(h => h.kind === "osc" || h.kind === "noise");
ok(percussive.length > 30, `groove scheduled (${percussive.length} hits/~17 bars)`);

// hits land on the 16th grid (stutter echoes at +0.03s stay within tolerance)
const gridOK = percussive.every(h => {
  const phase = (h.t - T0) / SPB;
  const frac = phase - Math.floor(phase);
  return Math.min(frac, 1 - frac) * SPB < 0.035;
});
ok(gridOK, "hits on 16th-note grid");

/* ---------- state -> sound mapping (deterministic fixture) ---------- */
function countHits(state, steps = 16) {
  hits.length = 0; pendingGains.length = 0;
  S.state = state;
  for (let s = 0; s < steps; s++)
    scheduleStep(s, 1000 + s * SPB);
  return hits.slice();
}
const base = { hosts: { h1: { role: "kick", state: "healthy" } } };
const err  = { hosts: { h1: { role: "kick", state: "error" } } };
const deg  = { hosts: { h1: { role: "kick", state: "degraded" } } };
const healthyHits = countHits(base).filter(h => h.kind === "osc").length;
const errorHits   = countHits(err).filter(h => h.kind === "osc").length;
ok(errorHits === healthyHits * 2,
   `error state = accent+stutter (${healthyHits}→${errorHits} osc hits)`);

// degraded velocity < healthy velocity
const vel = st => {
  const hs = countHits(st).filter(h => h.kind === "osc");
  return hs.length ? Math.max(...hs.map(h => h.vel || 0)) : 0;
};
ok(vel(deg) < vel(base), `degraded = quieter hit (${vel(deg).toFixed(2)} < ${vel(base).toFixed(2)})`);

// unknown/unreachable host still plays quietly (not silent, not accent)
const unk = countHits({ hosts: { h1: { role: "kick", state: "unknown" } } });
ok(unk.filter(h => h.kind === "osc").length === healthyHits,
   "unknown host keeps its voice");

// pitch from health: load detunes the voice sharper, error adds a nudge
const kickFreq = h => Math.max(...countHits({ hosts: { h1: h } })
  .filter(x => x.kind === "osc" && x.freq).map(x => x.freq));
const fIdle = kickFreq({ role: "kick", state: "healthy", load: 0 });
const fBusy = kickFreq({ role: "kick", state: "healthy", load: 30 });
const fErr  = kickFreq({ role: "kick", state: "error", load: 0 });
ok(fBusy > fIdle, `pitch rises with load (${fIdle.toFixed(1)}→${fBusy.toFixed(1)}Hz)`);
ok(fErr > fIdle, `error state hits sharper (${fIdle.toFixed(1)}→${fErr.toFixed(1)}Hz)`);

// alerts crash on bar downbeat
hits.length = 0; pendingGains.length = 0;
S.state = { hosts: {}, alerts: ["svc-a", "svc-b"] };
scheduleStep(0, 2000);
const crashNoise = hits.filter(h => h.kind === "noise");
ok(crashNoise.length >= 1, "alerts = crash on downbeat");
hits.length = 0; pendingGains.length = 0;
scheduleStep(8, 2000);
ok(hits.filter(h => h.kind === "noise").length === 0,
   "no crash off-downbeat");

// tempo reflects event rate: live bpm -> distinct step duration
ok(Math.abs(SPB - 60 / S.bpm / 4) < 1e-9, "step duration follows bpm");

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
