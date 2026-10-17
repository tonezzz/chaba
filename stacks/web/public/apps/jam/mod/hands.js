/* jam mod: hands — MediaPipe HandLandmarker (in-browser WASM, frames
   never leave the device). Air-drum: fast downward wrist motion =
   strike; hand height = continuous value for note-style targets.
   Loads tasks-vision lazily from /apps/vendor/mediapipe/ (vendored —
   CDN/offline no longer a dependency). */
"use strict";
JAM.register("hands", {
  stream: null, landmarker: null, raf: 0,
  lastY: { Left: null, Right: null }, lastT: { Left: 0, Right: 0 },
  steps: {}, lastSeen: {}, lastEmit: {}, glideWd: 0,

  async init() {
    const video = document.getElementById("cam");
    this.stream = await navigator.mediaDevices.getUserMedia({
      video: { width: 320, height: 240, facingMode: "user" }, audio: false });
    video.srcObject = this.stream; video.style.display = "block";
    await video.play();

    const mp = await import("/apps/vendor/mediapipe/vision_bundle.mjs");
    const files = await mp.FilesetResolver.forVisionTasks(
      "/apps/vendor/mediapipe/");
    // GPU delegate can hang forever (iOS Safari, headless/webgl-blocked
    // chromium) — race the create, retry on CPU if it doesn't resolve.
    const mk = (delegate) => mp.HandLandmarker.createFromOptions(files, {
      baseOptions: {
        modelAssetPath: "/apps/vendor/mediapipe/hand_landmarker.task",
        delegate },
      runningMode: "VIDEO", numHands: 2 });
    try {
      this.landmarker = await Promise.race([
        mk("GPU"),
        new Promise((_, rej) => setTimeout(
          () => rej(new Error("GPU delegate timeout")), 15000)),
      ]);
    } catch (e) {
      console.warn("hands: GPU delegate failed, retrying on CPU:", e);
      this.landmarker = await mk("CPU");
    }

    const loop = () => {
      this.raf = requestAnimationFrame(loop);
      if (video.readyState < 2) return;
      const res = this.landmarker.detectForVideo(video, performance.now());
      for (const lm of res.landmarks || []) {
        const hand = (res.handednesses?.[res.landmarks.indexOf(lm)]?.[0]
                      ?.categoryName) || "Right";
        const wrist = lm[0];                 // wrist landmark
        const y = wrist.y, now = performance.now();
        const lastY = this.lastY[hand];
        // downward strike: y increases fast (>0.35 frame-space / 100ms)
        if (lastY !== null && y - lastY > 0.05 &&
            now - this.lastT[hand] > 120) {
          this.lastT[hand] = now;
          const v = Math.min(1, (y - lastY) * 8);
          JAM.emit(`hand-strike-${hand[0]}`, v);
          JAM.hud(`✋ ${hand} strike v=${v.toFixed(2)}`);
        }
        this.lastY[hand] = y;
        // theremin: one shared gliding tone — presence = sound
        const side = hand[0], ac = JAM._actx();
        if (!JAM.tonesOff) {
          const tone = JAM._tone("hands-hand", "sine");
          const scale = JAM._SCALES.blue;
          const deg = Math.min(7, Math.max(0, ((1 - y) * 8) | 0));
          tone.o.frequency.setTargetAtTime(
            JAM._NOTE(48 + scale[deg % scale.length] +
                      12 * (deg / scale.length | 0)),
            ac.currentTime, 0.09);
          tone.g.gain.setTargetAtTime(0.08, ac.currentTime, 0.1);
          this.lastSeen[side] = now;
        }
        if (deg !== (this.steps[side] ?? -1) &&
            now - (this.lastEmit[side] || 0) > 250) {
          this.steps[side] = deg;
          this.lastEmit[side] = now;
          JAM.emit(`hand-move-${side}`, deg / 7);
        }
      }
    };
    loop();
    // theremin watchdog: hand out of frame ~350ms -> tone fades out
    this.glideWd = setInterval(() => {
      const now = performance.now(), ac = JAM._actx();
      const any = Math.max(this.lastSeen.L || 0, this.lastSeen.R || 0);
      if (any && now - any > 350)
        JAM._tone("hands-hand").g.gain.setTargetAtTime(0, ac.currentTime, 0.12);
    }, 200);
    JAM.hud("📷 hands on — slap the air: left=kick right=snare (rebind in matrix)");
  },

  destroy() {
    cancelAnimationFrame(this.raf);
    this.stream?.getTracks().forEach(t => t.stop());
    document.getElementById("cam").style.display = "none";
    this.landmarker?.close(); this.landmarker = null;
    clearInterval(this.glideWd);
    JAM._toneDrop("hands-hand"); JAM._toneDrop("hands-L"); JAM._toneDrop("hands-R");
    this.lastY = { Left: null, Right: null };
    this.steps = {}; this.lastSeen = {}; this.lastEmit = {};
  },
});
