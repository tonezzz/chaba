/* jam mod: sax — air saxophone. Hand height picks notes on the blues
   scale with a portamento glide between them, so even sloppy hand waves
   come out sounding like a phrase. Forgiving by design, not accurate.

     hand height   -> note (blue scale, ~2 octaves, legato glide)
     hand wiggle   -> vibrato depth (still air = clean tone)
     fist          -> growl (opens the filter, adds bite)
     pinch         -> octave up/down toggle
     hand leaves   -> release (note breathes out)

   Feed: same gesture relay contract as remote — joins the vcast-N room
   when jam runs inside a screen (?screen=N), else gesture-live. */
"use strict";
JAM.register("sax", {
  ws: null, retry: 0, v: null, oct: 0,
  lastX: 0.5, wig: 0, lastY: null, midi: null,

  voice() {
    if (this.v) return this.v;
    const ac = JAM._actx();
    const g = ac.createGain(); g.gain.value = 0;
    const lp = ac.createBiquadFilter();
    lp.type = "lowpass"; lp.frequency.value = 1400; lp.Q.value = 1.1;
    // two slightly detuned saws = reed body; vibrato LFO rides the detune
    const o1 = ac.createOscillator(); o1.type = "sawtooth";
    const o2 = ac.createOscillator(); o2.type = "sawtooth"; o2.detune.value = 9;
    const vib = ac.createOscillator(); vib.frequency.value = 5.4;
    const vibG = ac.createGain(); vibG.gain.value = 4;      // cents of warble
    vib.connect(vibG); vibG.connect(o1.detune); vibG.connect(o2.detune);
    o1.connect(g); o2.connect(g); g.connect(lp); lp.connect(ac.destination);
    o1.start(); o2.start(); vib.start();
    this.v = { o1, o2, g, lp, vib, vibG };
    return this.v;
  },

  gate(on) {
    const v = this.v, ac = JAM._actx();
    // soft attack so notes bloom like breath; slower release = sax decay
    v.g.gain.setTargetAtTime(on ? 0.14 : 0, ac.currentTime, on ? 0.06 : 0.18);
  },

  growl(on) {
    const v = this.v, ac = JAM._actx();
    v.lp.frequency.setTargetAtTime(on ? 3400 : 1400, ac.currentTime, 0.06);
    v.vibG.gain.setTargetAtTime(on ? 18 : 4, ac.currentTime, 0.08);
    JAM.hud(on ? "🎷 growl!" : "🎷");
  },

  connect() {
    const scr = new URLSearchParams(location.search).get("screen");
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const url = scr
      ? `${proto}://${location.host}/api/input-bridge/ws`
      : `${proto}://${location.host}/apps/gesture-live/ws?role=screen`;
    const ws = new WebSocket(url);
    this.ws = ws;
    ws.onopen = () => {
      this.retry = 0;
      if (scr) ws.send(JSON.stringify({ type: "join", room: "vcast-" + scr }));
      JAM.hud("🎷 sax linked — move your hand up/down, fist to growl, pinch for octave");
    };
    ws.onclose = ws.onerror = () => {
      JAM.hud("🎷 relay offline — retrying");
      setTimeout(() => this.ws && this.connect(),
                 Math.min(8000, 500 * 2 ** this.retry++));
    };
    ws.onmessage = ev => this.onMsg(ev.data);
  },

  onMsg(data) {
    let m; try { m = JSON.parse(data); } catch { return; }
    if (m.type !== "gesture") return;
    const ac = JAM._actx();
    if (m.gone || m.x === undefined) { this.gate(0); this.midi = null; return; }

    // lateral wiggle drives vibrato — a held-still hand sings clean,
    // a shaking hand warbles like a player pushing the note
    const dx = Math.abs(m.x - this.lastX); this.lastX = m.x;
    this.wig = this.wig * 0.9 + dx * 14;
    const v = this.voice();
    v.vibG.gain.setTargetAtTime(Math.min(26, 4 + this.wig * 50),
                                ac.currentTime, 0.12);

    // y -> blue scale, two octaves, root Bb-ish — quantize to the nearest
    // step so it's impossible to land between notes; the glide sells it
    const scale = JAM._SCALES.blue;
    const steps = scale.length * 2;
    const n = Math.min(steps - 1, Math.max(0, Math.round((1 - m.y) * (steps - 1))));
    const midi = 46 + scale[n % scale.length]
               + 12 * Math.floor(n / scale.length) + this.oct * 12;
    if (midi !== this.midi) {
      this.midi = midi;
      const f = JAM._NOTE(midi);
      v.o1.frequency.setTargetAtTime(f, ac.currentTime, 0.055);
      v.o2.frequency.setTargetAtTime(f * 1.004, ac.currentTime, 0.055);
      JAM.hud(`🎷 ${midi % 12 === 10 ? "B♭" : ""}note ${midi}`);
    }
    this.gate(1);

    if (m.action === "fist_start") this.growl(true);
    else if (m.action === "fist_end") this.growl(false);
    else if (m.action === "pinch") {
      this.oct = this.oct ? 0 : 1;
      JAM.hud(this.oct ? "🎷 octave up" : "🎷 home octave");
    }
  },

  init() {
    JAM.tonesOff = true;   // remote's theremin ducks while sax owns melody
    this.voice();
    this.connect();
    JAM.hud("🎷 sax on — raise your hand and play");
  },

  destroy() {
    JAM.tonesOff = false;
    const ws = this.ws; this.ws = null;
    ws && ws.close();
    const v = this.v;
    if (v) {
      this.v = null;
      try {
        v.g.gain.setTargetAtTime(0, JAM._actx().currentTime, 0.08);
        setTimeout(() => { v.o1.stop(); v.o2.stop(); v.vib.stop(); }, 500);
      } catch {}
    }
    this.midi = null;
  },
});
