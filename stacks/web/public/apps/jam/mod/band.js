/* jam mod: band — "AUTO TUNE" act. Plays a base-music track from the
   percussion style library; your moves jam on top.

   Tracks (swipe hand fast L/R to change):
     Blues Jam · Metallica · Rock · Polyphia · Gary Moore · Queen
     Funky · Electronic · EDM

   The track ALWAYS plays while this module is on — that's the point
   (module toggle = the off switch). Movement steers it:
     strikes -> +energy -> faster + fills + call-and-response echo
     swipe L/R -> previous/next track
     arm-up R -> solo run, arm-up L -> bass run
     smile -> sparkle stab (like-signal)
   hand-move presence does NOT feed the band — presence = theremin only. */
"use strict";
JAM.register("band", {
  timer: 0, bpm: 100, style: 0, step: 0, nextT: 0,
  energy: 0.55, hits: 0, soloUntil: 0, hudT: 0,
  echo: [], barStart: 0,

  /* per-16th-step drum grids (velocity 0..1) + swing + riff notes
     {s:step, d:blues-scale degree, b:bend}. Ported from percussion library. */
  TRACKS: [
    { name: "Blues Jam", bpm: 84, swing: 0.16,
      kick: [1,0,0,0,0,0,0,1,0,0,1,0,0,0,0,0],
      snare:[0,0,0,0,1,0,0,0.3,0,0,0,0,1,0,0,0],
      hat:  [1,0,1,1,0,1,1,0,1,0,1,1,0,1,1,0],
      riff: [{s:0,d:0,b:1},{s:4,d:3},{s:8,d:5,b:1},{s:12,d:4}] },
    { name: "Metallica", bpm: 150, swing: 0,
      kick: [1,0,0,1,0,0,0,0,1,0,0,1,0,0,0,0],
      snare:[0,0,0,0,1,0,0,0,0,0,0,0,1,0,0,0],
      hat:  [1,0,1,0,1,0,1,0,1,0,1,0,1,0,1,0],
      crash:[1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
      riff: [{s:0,d:0},{s:1,d:0},{s:3,d:3},{s:6,d:0},{s:7,d:0},
             {s:10,d:5},{s:12,d:4},{s:14,d:0}] },
    { name: "Rock", bpm: 105, swing: 0,
      kick: [1,0,0,0,1,0,0,0,1,0,0,0,1,0,0,0],
      snare:[0,0,0,0,1,0,0,0,0,0,0,0,1,0,0,0],
      hat:  [1,0,1,0,1,0,1,0,1,0,1,0,1,0,1,0],
      tom:  [0,0,0,0,0,0,0,0,0,0,0,0,0,0,1,0],
      crash:[1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
      riff: [{s:0,d:0},{s:3,d:3},{s:6,d:0},{s:7,d:4},{s:10,d:5},{s:14,d:0}] },
    { name: "Polyphia", bpm: 112, swing: 0,   // trap hats + virtuoso lead
      kick: [1,0,0,0,0,0,1,0,0,0,1,0,0,0,0,0],
      snare:[0,0,0,0,0,0,0,0,1,0,0,0,0,0,0,0],
      hat:  [1,0,1,0,1,0,1,0,1,0,1,0,1,0,1,1],
      shaker:[0,0,0,0,0,0,0,1,0,0,0,0,0,0,0,1],
      riff: [{s:0,d:0},{s:2,d:6},{s:4,d:4},{s:6,d:6},{s:8,d:7},
             {s:10,d:9},{s:12,d:11},{s:14,d:6}],
      harmonize: true },
    { name: "Gary Moore", bpm: 72, swing: 0.12,   // slow blues bends
      kick: [1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
      snare:[0,0,0,0,0,0,0,0,0.7,0,0,0,0,0,0,0],
      hat:  [1,0,0,0,1,0,0,0,1,0,0,0,1,0,0,0],
      crash:[1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
      riff: [{s:0,d:0,b:1},{s:6,d:4,b:2},{s:12,d:5,b:1}],
      leadSlow: true },
    { name: "Queen", bpm: 96, swing: 0,           // stomp-stomp-clap feel
      kick: [1,0,1,0,0,0,0,0,1,0,1,0,0,0,0,0],
      clap: [0,0,0,0,1,0,0,0,0,0,0,0,1,0,0,0],
      hat:  [0,0,1,0,0,0,1,0,0,0,1,0,0,0,1,0],
      crash:[1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
      riff: [{s:0,d:0},{s:6,d:3},{s:8,d:5},{s:14,d:7}] },
    { name: "Funky", bpm: 98, swing: 0.12,
      kick: [1,0,0,0,0,0,0,1,0,0,1,0,0,0,0,0],
      snare:[0,0,0.3,0,1,0,0.3,0,0,0,0.3,0,1,0,0.4,0],
      hat:  [1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,0],
      rim:  [0,0,0,0,0,0,0,0,0,0,0,0,0,0,1,0],
      riff: [{s:0,d:0},{s:3,d:6},{s:7,d:3},{s:10,d:6},{s:14,d:4}] },
    { name: "Electronic", bpm: 120, swing: 0,
      kick: [1,0,0,0,1,0,0,0,1,0,0,0,1,0,0,0],
      clap: [0,0,0,0,1,0,0,0,0,0,0,0,1,0,0,0],
      hat:  [0,0,1,0,0,0,1,0,0,0,1,0,0,0,1,0],
      shaker:[1,0,1,0,1,0,1,0,1,0,1,0,1,0,1,0],
      riff: [{s:0,d:0},{s:4,d:0},{s:8,d:3},{s:12,d:4}] },
    { name: "EDM", bpm: 128, swing: 0,
      kick: [1,0,0,0,1,0,0,0,1,0,0,0,1,0,0,0],
      clap: [0,0,0,0,1,0,0,0,0,0,0,0,0,0,0,0],
      hat:  [0,0,1,0,0,0,1,0,0,0,1,0,0,0,1,1],
      crash:[1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
      tom:  [0,0,0,0,0,0,0,0,0,0,0,0,0,0.5,0.6,0.8],
      riff: [{s:0,d:0},{s:4,d:3},{s:8,d:4},{s:12,d:6}] },
  ],

  // grid name -> jam voice (ride/tamb map to closest)
  VMAP: { kick: "kick", snare: "snare", hat: "hat", tom: "tom",
          crash: "crash", clap: "clap", rim: "rim", shaker: "shaker",
          ride: "hat", tamb: "shaker" },

  degF(d, oct = 1) {
    const sc = JAM._SCALES.blue;
    return JAM._NOTE(45 + 12 * (oct + Math.floor(d / sc.length)) +
                     sc[d % sc.length]);
  },

  async init(J) {
    this.step = 0; this.hits = 0; this.echo = []; this.soloUntil = 0;
    this.energy = 0.55;
    const tr = this.TRACKS[this.style];
    this.bpm = tr.bpm;
    this.nextT = J._actx().currentTime + 0.1;
    this.timer = setInterval(() => this.tick(), 30);
    J.hud(`🎹 "${tr.name}" playing — swipe hand fast L/R for tracks · drum to jam`);
  },

  setStyle(i) {
    this.style = (i + this.TRACKS.length) % this.TRACKS.length;
    const tr = this.TRACKS[this.style];
    this.step = 0;                       // restart pattern on the bar
    JAM.hud(`🎹 track → ${tr.name} (${tr.bpm}bpm)`);
    JAM._v.riser(JAM._actx().currentTime, 0.25);
  },

  fill(t, spb) {
    const v = JAM._v, scale = JAM._SCALES.blue;
    if (Math.random() < 0.5) {
      for (let i = 0; i < 4; i++) v.tom(t + i * spb * 2, 0.6 - i * 0.1);
    } else {
      this.soloUntil = t + 8 * spb;
      for (let i = 0; i < 8; i++)
        v.bell(t + i * spb, this.degF(i * 2, 1), 0.25);
    }
  },

  tick() {
    const ac = JAM._actx(), v = JAM._v, tr = this.TRACKS[this.style];
    const spb = 60 / this.bpm / 4;
    // energy only modulates tempo a little + gates fills — track always plays
    const tempo = tr.bpm * (0.92 + Math.min(0.35, this.energy * 0.35));
    this.bpm += (tempo - this.bpm) * 0.08;
    this.energy *= 0.997;
    // throttled-tab guard: drop backlog instead of replaying it
    if (this.nextT < ac.currentTime - 0.2) this.nextT = ac.currentTime;
    let guard = 0;
    while (this.nextT < ac.currentTime + 0.12 && guard++ < 32) {
      let t = this.nextT;
      const s16 = this.step % 16, bar = (this.step / 16) | 0;
      if (tr.swing && s16 % 2) t += spb * tr.swing;      // swing the off-16ths
      // drum grid
      for (const k in tr) {
        const row = tr[k], fn = this.VMAP[k];
        if (!fn || !Array.isArray(row) || !row[s16]) continue;
        v[fn](t, (row[s16] < 1 ? row[s16] : 1) * 0.6);
      }
      if (s16 === 0) this.barStart = t;
      // riff melody — the "song" part
      for (const r of tr.riff || []) {
        if (r.s !== s16) continue;
        const f = this.degF(r.d, tr.leadSlow ? 1 : 2);
        v.bell(t, f, tr.leadSlow ? 0.3 : 0.22, tr.leadSlow ? spb * 6 : spb * 2.5);
        if (tr.harmonize) v.bell(t, this.degF(r.d + 2, 2), 0.14, spb * 2);
      }
      // strikes this bar -> fill next bar
      if (s16 === 15) {
        if (this.hits >= 3 || Math.random() < this.energy * 0.06)
          this.fill(t + spb, spb);
        const inBar = this.echo.filter(t0 => t0 >= this.barStart && t0 <= t);
        if (inBar.length >= 2 && this.energy > 0.55) {
          const qs = [...new Set(inBar.map(t0 =>
            Math.min(15, Math.max(0, Math.round((t0 - this.barStart) / spb)))))]
            .sort((a, b) => a - b).slice(0, 8);
          qs.forEach((q, i) =>
            v.bell(t + spb + q * spb, this.degF((i * 2) % 12, 2), 0.2, spb * 2));
          JAM.hud("🎹 echoing your riff ↩");
        }
        this.echo = []; this.hits = 0;
      }
      this.step++;
      this.nextT += spb;
    }
    const now = performance.now();
    if (now - this.hudT > 2500) {
      this.hudT = now;
      JAM.hud(`🎹 ${tr.name} · ${this.bpm | 0}bpm · drum to speed up · swipe = track`);
    }
  },

  onEvent(evt, val) {
    if (evt === "swipe-L") return this.setStyle(this.style - 1);
    if (evt === "swipe-R") return this.setStyle(this.style + 1);
    if (evt === "arm-up-L") {
      const t = JAM._actx().currentTime, spb = 60 / this.bpm / 4;
      for (let i = 0; i < 4; i++)
        JAM._v.pluck(t + i * spb * 2, this.degF(i * 3, 0), 0.55);
      return JAM.hud("🎹 arm L → bass run");
    }
    if (evt === "arm-up-R") {
      this.fill(JAM._actx().currentTime + 0.05, 60 / this.bpm / 4);
      return JAM.hud("🎹 arm R → solo run");
    }
    if (evt === "smile") {
      const t = JAM._actx().currentTime;
      JAM._v.stab(t, [0, 3, 7, 10].map(s => JAM._NOTE(57 + s)), 0.25);
      return JAM.hud("🎹 🙂 heard");
    }
    // hand-move = presence only — never feeds the band
    if (evt.startsWith("hand-move")) return;
    if (evt.startsWith("hand-strike") || evt === "clap" || evt === "nod"
        || evt === "jump") {
      this.energy = Math.min(1, this.energy + 0.09);
      this.hits++;
      this.echo.push(JAM._actx().currentTime);
    }
  },

  destroy() {
    clearInterval(this.timer);
    JAM.hud("band off — back to RAW act");
  },
});
