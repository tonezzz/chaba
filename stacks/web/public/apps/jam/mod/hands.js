/* jam mod: hands — MediaPipe HandLandmarker (in-browser WASM, frames
   never leave the device). Air-drum: fast downward wrist motion =
   strike; hand height = continuous value for note-style targets.
   Loads tasks-vision lazily from CDN — offline = module disabled. */
"use strict";
JAM.register("hands", {
  stream: null, landmarker: null, raf: 0,
  lastY: { Left: null, Right: null }, lastT: { Left: 0, Right: 0 },
  steps: {}, lastSeen: {}, glideWd: 0,

  async init() {
    const video = document.getElementById("cam");
    this.stream = await navigator.mediaDevices.getUserMedia({
      video: { width: 320, height: 240, facingMode: "user" }, audio: false });
    video.srcObject = this.stream; video.style.display = "block";
    await video.play();

    const mp = await import(
      "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/vision_bundle.mjs");
    const files = await mp.FilesetResolver.forVisionTasks(
      "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/wasm");
    this.landmarker = await mp.HandLandmarker.createFromOptions(files, {
      baseOptions: {
        modelAssetPath:
          "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task",
        delegate: "GPU" },
      runningMode: "VIDEO", numHands: 2 });

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
        // theremin: one sustained gliding tone per hand — presence = sound
        const side = hand[0], ac = JAM._actx();
        const tone = JAM._tone("hands-" + side,
                               side === "L" ? "sine" : "triangle");
        const scale = JAM._SCALES.blue;
        const deg = Math.min(9, Math.max(0, ((1 - y) * 10) | 0));
        tone.o.frequency.setTargetAtTime(
          JAM._NOTE((side === "L" ? 57 : 45) +
                    scale[deg % scale.length] + 12 * (deg / scale.length | 0)),
          ac.currentTime, 0.07);
        tone.g.gain.setTargetAtTime(0.15, ac.currentTime, 0.08);
        this.lastSeen[side] = now;
        if (deg !== (this.steps[side] ?? -1)) {
          this.steps[side] = deg;
          JAM.emit(`hand-move-${side}`, deg / 9);
        }
      }
    };
    loop();
    // theremin watchdog: hand out of frame ~350ms -> tone fades out
    this.glideWd = setInterval(() => {
      const now = performance.now(), ac = JAM._actx();
      for (const s of ["L", "R"]) {
        if (!this.lastSeen[s]) continue;
        const v = JAM._tone("hands-" + s);
        if (v.g.gain.value > 0.01 && now - this.lastSeen[s] > 350)
          v.g.gain.setTargetAtTime(0, ac.currentTime, 0.12);
      }
    }, 200);
    JAM.hud("📷 hands on — slap the air: left=kick right=snare (rebind in matrix)");
  },

  destroy() {
    cancelAnimationFrame(this.raf);
    this.stream?.getTracks().forEach(t => t.stop());
    document.getElementById("cam").style.display = "none";
    this.landmarker?.close(); this.landmarker = null;
    clearInterval(this.glideWd);
    JAM._toneDrop("hands-L"); JAM._toneDrop("hands-R");
    this.lastY = { Left: null, Right: null };
    this.steps = {}; this.lastSeen = {};
  },
});
