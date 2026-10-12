/* jam mod: mic — WebAudio analyser on getUserMedia audio. Onset =
   energy spike -> 'clap' event; sustained pitch -> 'hum-note' (val =
   scale degree 0..1 across the detectable range). All local. */
"use strict";
JAM.register("mic", {
  stream: null, node: null, analyser: null, raf: 0,
  _prev: 0, _cool: 0,

  async init() {
    this.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const src = S.ac ? S.ac : actx();
    this.node = src.createMediaStreamSource(this.stream);
    this.analyser = src.createAnalyser();
    this.analyser.fftSize = 1024;
    this.node.connect(this.analyser);          // analysis only — NOT to speakers
    const buf = new Float32Array(this.analyser.fftSize);
    const tdata = new Uint8Array(this.analyser.frequencyBinCount);

    const loop = () => {
      this.raf = requestAnimationFrame(loop);
      this.analyser.getFloatTimeDomainData(buf);
      let e = 0;
      for (let i = 0; i < buf.length; i += 4) e += buf[i] * buf[i];
      e = Math.sqrt(e / (buf.length / 4));      // rms
      const now = performance.now();
      if (e > 0.12 && e > this._prev * 2 && now > this._cool) {
        this._cool = now + 180;
        JAM.emit("clap", Math.min(1, e * 4));
        JAM.hud(`👏 clap e=${e.toFixed(2)}`);
      }
      this._prev = e;
      // rough pitch: dominant bin -> midi-ish position
      this.analyser.getByteFrequencyData(tdata);
      let peak = 0, pi = 0;
      for (let i = 4; i < tdata.length / 2; i++)
        if (tdata[i] > peak) { peak = tdata[i]; pi = i; }
      if (peak > 140 && e > 0.02 && e < 0.12) {  // humming range, not clap
        const f = pi * src.sampleRate / this.analyser.fftSize;
        if (f > 60 && f < 1200)
          JAM.emit("hum-note", Math.min(1, Math.log2(f / 80) / 4));
      }
    };
    loop();
    JAM.hud("🎤 mic on — clap = clap, hum = lead note (rebind in matrix)");
  },

  destroy() {
    cancelAnimationFrame(this.raf);
    this.node?.disconnect();
    this.stream?.getTracks().forEach(t => t.stop());
  },
});
