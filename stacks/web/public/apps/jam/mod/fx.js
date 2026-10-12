/* jam mod: fx — insert effects chain between the mix bus (S.fxIn) and
   destination. Toggle-style; off = direct wire. All client-side. */
"use strict";
JAM.register("fx", {
  nodes: {}, live: {},

  init() {
    // rebuild the chain each enable so toggles start clean
    this.rebuild();
  },
  destroy() {
    for (const k of Object.keys(this.nodes)) this.nodes[k].disconnect();
    this.nodes = {}; this.live = {};
    S.fxIn.disconnect();
    S.fxIn.connect(S.ac.destination);
  },

  rebuild() {
    // fxIn -> [delay] -> [verb] -> [crush] -> [stutter gate] -> destination
    S.fxIn.disconnect();
    let tail = S.fxIn;
    const mk = n => { tail.connect(n); tail = n; };
    if (this.live["fx-delay"]) {
      const d = S.ac.createDelay(1), fb = S.ac.createGain(),
            wet = S.ac.createGain(), dry = S.ac.createGain();
      d.delayTime.value = 0.28; fb.gain.value = 0.35;
      wet.gain.value = 0.4; dry.gain.value = 1;
      const mix = S.ac.createGain();
      tail.connect(d); d.connect(fb).connect(d); d.connect(wet).connect(mix);
      tail.connect(dry).connect(mix);
      this.nodes.delay = d; this.nodes.delayFb = fb; tail = mix;
    }
    if (this.live["fx-verb"]) {
      // cheap reverb: 4 parallel delays w/ different times + lowpass
      const mix = S.ac.createGain(), lp = S.ac.createBiquadFilter();
      lp.type = "lowpass"; lp.frequency.value = 3200;
      const dry = S.ac.createGain();
      tail.connect(dry).connect(mix);
      for (const [dt, g] of [[0.09, .3], [0.17, .22], [0.23, .18], [0.31, .12]]) {
        const dl = S.ac.createDelay(0.5), wg = S.ac.createGain();
        dl.delayTime.value = dt; wg.gain.value = g;
        tail.connect(dl).connect(wg).connect(lp);
      }
      lp.connect(mix);
      this.nodes.verb = lp; tail = mix;
    }
    if (this.live["fx-crush"]) {
      const ws = S.ac.createWaveShaper();
      const c = new Float32Array(256);
      for (let i = 0; i < 256; i++) {
        const x = i / 127.5 - 1;
        c[i] = Math.sign(x) * Math.floor(Math.abs(x) * 6) / 6;  // 6-step quantize
      }
      ws.curve = c;
      tail.connect(ws); this.nodes.crush = ws; tail = ws;
    }
    if (this.live["fx-stutter"]) {
      const g = S.ac.createGain(), lfo = S.ac.createOscillator(),
            lg = S.ac.createGain();
      lfo.type = "square"; lfo.frequency.value = 12;
      lg.gain.value = 0.5; g.gain.value = 0.5;
      lfo.connect(lg).connect(g.gain);
      tail.connect(g); lfo.start();
      this.nodes.stutter = g; this.nodes.stutterLfo = lfo; tail = g;
    }
    tail.connect(S.ac.destination);
  },

  toggleFx(id, btn) {
    this.live[id] = !this.live[id];
    if (btn) btn.classList.toggle("on", this.live[id]);
    this.rebuild();
    JAM.hud(id + (this.live[id] ? " on" : " off"));
  },
});
