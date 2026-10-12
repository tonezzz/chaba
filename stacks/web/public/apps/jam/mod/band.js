/* jam mod: band — the "Auto Tune" act. A master clock plays a backing
   groove (drums + bass + chords) and the player jams on top; the app
   reads IMPLICIT feedback and adapts:

     smile        -> like-signal: keep this style, sparkle stab, +energy
     hand strikes -> +energy -> faster tempo, more fills
     on-bar hits  -> fill reward at next bar boundary
     swipe-L/R    -> previous/next style (voice: "band, change!")
     lean         -> reserved for filter control

   Voices are reused from the core via JAM._v / JAM._actx / JAM._NOTE. */
"use strict";
JAM.register("band", {
  timer: 0, bpm: 100, targetBpm: 100, style: 0, step: 0, nextT: 0,
  energy: 0.3, hits: 0, soloUntil: 0, hudT: 0,
  echo: [], barStart: 0,

  // per-16th-step patterns; bass values = blues-scale degrees (null = rest)
  STYLES: [
    { name: "lofi",  bpm: 82,  kick: [0, 7, 10],        snare: [4, 12],      hat: [2, 6, 10, 14],
      bass: [0,null,0,null, 3,null,0,5, null,0,null,7, 3,null,null,null],
      chordBars: 2 },
    { name: "house", bpm: 118, kick: [0, 4, 8, 12],     snare: [4, 12],      hat: [2, 6, 10, 14],
      bass: [0,null,0,3, null,0,5,null, 0,null,0,7, null,5,3,null],
      chordBars: 4 },
    { name: "funk",  bpm: 102, kick: [0, 6, 8, 14],     snare: [4, 12, 15],  hat: [0,2,4,6,8,10,12,14],
      bass: [0,null,3,null, 5,null,0,7, null,3,null,5, 7,null,10,null],
      chordBars: 4 },
    { name: "rock",  bpm: 132, kick: [0, 3, 8, 11],     snare: [4, 12],      hat: [0,2,4,6,8,10,12,14],
      bass: [0,0,3,null, 0,0,5,null, 0,0,7,null, 10,10,12,null],
      chordBars: 2 },
  ],

  async init(J) {
    this.step = 0;
    this.nextT = J._actx().currentTime + 0.1;
    this.timer = setInterval(() => this.tick(), 30);
    const st = this.STYLES[this.style];
    this.bpm = this.targetBpm = st.bpm;
    J.hud(`🎹 AUTO TUNE — "${st.name}" backing live · swipe hand fast L/R to change style · smile = you like it`);
  },

  setStyle(i) {
    this.style = (i + this.STYLES.length) % this.STYLES.length;
    const st = this.STYLES[this.style];
    this.targetBpm = st.bpm * (0.85 + this.energy * 0.45);
    JAM.hud(`🎹 style → ${st.name} (${st.bpm}bpm base)`);
    JAM._v.riser(JAM._actx().currentTime, 0.3);
  },

  // a fast run: toms down or lead arpeggio up — the "surprise"
  fill(t, spb) {
    const v = JAM._v, scale = JAM._SCALES.blue, root = 57;
    if (Math.random() < 0.5) {
      for (let i = 0; i < 4; i++) v.tom(t + i * spb * 2, 0.7 - i * 0.12);
    } else {
      this.soloUntil = t + 8 * spb;
      for (let i = 0; i < 8; i++)
        v.lead(t + i * spb, JAM._NOTE(root + scale[(i * 2 + (Math.random() * 3 | 0)) % scale.length]),
               0.32, 0, spb * 1.4);
    }
  },

  tick() {
    const ac = JAM._actx(), v = JAM._v, st = this.STYLES[this.style];
    const scale = JAM._SCALES.blue, root = 45;
    this.bpm += (this.targetBpm - this.bpm) * 0.08;
    this.energy *= 0.996;                     // activity decays
    const spb = 60 / this.bpm / 4;            // 16th-note seconds
    while (this.nextT < ac.currentTime + 0.12) {
      const t = this.nextT, s16 = this.step % 16, bar = (this.step / 16) | 0;
      if (st.kick.includes(s16))  v.kick(t, 0.85);
      if (st.snare.includes(s16)) v.snare(t, 0.65);
      if (st.hat.includes(s16))   v.hat(t, 0.45, s16 === 14 && bar % 2 === 1);
      const b = st.bass[s16];
      if (b != null) v.bass(t, JAM._NOTE(root + scale[b % scale.length]), 0.45);
      if (s16 === 0 && bar % st.chordBars === 0)
        v.stab(t, [0, 3, 7].map(s => JAM._NOTE(root + 12 + s)), 0.22);
      if (s16 === 0) this.barStart = t;
      // the feedback payoff: hits in this bar -> fill next bar;
      // ambient surprise scales with energy
      if (s16 === 15) {
        const reward = this.hits >= 3;
        const surprise = Math.random() < 0.04 + this.energy * 0.08;
        if (reward || surprise) this.fill(t + spb, spb);
        // call-and-response: YOUR rhythm echoed as a melody next bar
        const inBar = this.echo.filter(t0 => t0 >= this.barStart && t0 <= t);
        if (inBar.length >= 2) {
          const qs = [...new Set(inBar.map(t0 =>
            Math.min(15, Math.max(0, Math.round((t0 - this.barStart) / spb)))))]
            .sort((a, b) => a - b).slice(0, 8);
          qs.forEach((q, i) =>
            v.lead(t + spb + q * spb,
                   JAM._NOTE(57 + scale[(i * 2) % scale.length]), 0.3, 0, spb * 2));
          JAM.hud("🎹 echoing your riff ↩");
        }
        this.echo = [];
        this.hits = 0;
      }
      this.step++;
      this.nextT += spb;
    }
    const now = performance.now();
    if (now - this.hudT > 2000) {
      this.hudT = now;
      JAM.hud(`🎹 ${st.name} · ${this.bpm | 0}bpm · energy ${(this.energy * 100) | 0}% — move faster to speed it up`);
    }
  },

  onEvent(evt, val) {
    const w = evt.startsWith("hand-move") ? 0.015
      : (evt.startsWith("hand-strike") || evt === "clap" || evt === "nod"
         || evt === "jump" || evt.startsWith("arm-up")) ? 0.09 : 0;
    if (w) {
      this.energy = Math.min(1, this.energy + w);
      if (w >= 0.09) {
        this.hits++;
        this.echo.push(JAM._actx().currentTime);   // rhythm to echo
      }
      // more movement -> faster music
      this.targetBpm = this.STYLES[this.style].bpm * (0.85 + this.energy * 0.45);
    }
    if (evt === "swipe-L") this.setStyle(this.style - 1);
    else if (evt === "swipe-R") this.setStyle(this.style + 1);
    else if (evt === "arm-up-L") {
      const t = JAM._actx().currentTime, spb = 60 / this.bpm / 4;
      for (let i = 0; i < 4; i++)
        JAM._v.bass(t + i * spb * 2, JAM._NOTE(36 + i * 3), 0.6);
      JAM.hud("🎹 arm L → bass run");
    } else if (evt === "arm-up-R") {
      this.fill(JAM._actx().currentTime + 0.05, 60 / this.bpm / 4);
      JAM.hud("🎹 arm R → solo run");
    }
    else if (evt === "smile") {          // like-signal: reward the moment
      this.energy = Math.min(1, this.energy + 0.2);
      const t = JAM._actx().currentTime;
      JAM._v.stab(t, [0, 3, 7, 10].map(s => JAM._NOTE(57 + s)), 0.3);
      JAM.hud("🎹 🙂 heard — keeping this vibe");
    }
  },

  destroy() {
    clearInterval(this.timer);
    JAM.hud("band off — back to RAW act");
  },
});
