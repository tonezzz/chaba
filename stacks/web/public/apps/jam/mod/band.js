/* jam mod: band — "AUTO TUNE" act. Plays ONE base-music track at a fixed
   tempo. Swipe hand fast L/R to change track. That is ALL it does.

     Blues Jam · Metallica · Rock · Polyphia · Gary Moore · Queen
     Funky · Electronic · EDM

   No energy model, no fills, no echo, no solo runs, no gesture-triggered
   sounds — the screaming came from those paths; they are gone, not gated. */
"use strict";
JAM.register("band", {
  timer: 0, bpm: 100, style: 0, step: 0, nextT: 0,

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
    this.step = 0;
    const tr = this.TRACKS[this.style];
    this.bpm = tr.bpm;
    this.nextT = J._actx().currentTime + 0.1;
    this.timer = setInterval(() => this.tick(), 30);
    J.hud(`🎹 "${tr.name}" — swipe hand fast L/R to change track`);
  },

  setStyle(i) {
    this.style = (i + this.TRACKS.length) % this.TRACKS.length;
    const tr = this.TRACKS[this.style];
    this.bpm = tr.bpm;
    this.step = 0;
    this.nextT = JAM._actx().currentTime + 0.1;   // clean restart on the bar
    JAM.hud(`🎹 track → ${tr.name} (${tr.bpm}bpm)`);
  },

  tick() {
    const ac = JAM._actx(), v = JAM._v, tr = this.TRACKS[this.style];
    const spb = 60 / this.bpm / 4;
    // throttled-tab guard: drop backlog instead of replaying it
    if (this.nextT < ac.currentTime - 0.2) this.nextT = ac.currentTime;
    let guard = 0;
    while (this.nextT < ac.currentTime + 0.12 && guard++ < 32) {
      let t = this.nextT;
      const s16 = this.step % 16;
      if (tr.swing && s16 % 2) t += spb * tr.swing;      // swing the off-16ths
      for (const k in tr) {
        const row = tr[k], fn = this.VMAP[k];
        if (!fn || !Array.isArray(row) || !row[s16]) continue;
        v[fn](t, (row[s16] < 1 ? row[s16] : 1) * 0.6);
      }
      for (const r of tr.riff || []) {
        if (r.s !== s16) continue;
        const f = this.degF(r.d, tr.leadSlow ? 1 : 2);
        v.bell(t, f, tr.leadSlow ? 0.3 : 0.22, tr.leadSlow ? spb * 6 : spb * 2.5);
        if (tr.harmonize) v.bell(t, this.degF(r.d + 2, 2), 0.14, spb * 2);
      }
      this.step++;
      this.nextT += spb;
    }
  },

  onEvent(evt) {
    if (evt === "swipe-L") this.setStyle(this.style - 1);
    if (evt === "swipe-R") this.setStyle(this.style + 1);
    // everything else is ignored — no gesture makes sound except swipe
  },

  destroy() {
    clearInterval(this.timer);
    JAM.hud("band off — back to RAW act");
  },
});
