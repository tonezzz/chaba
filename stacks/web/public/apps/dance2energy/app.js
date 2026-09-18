// Main entry point — wires pose estimation, flow field, and renderer together.

import { initPose, startCamera, detectFrame, consumeNewPose,
         getPrev, getCur } from "./pose.js";
import { buildFlowField } from "./flowfield.js";
import * as renderer from "./renderer.js";

const W = 1920, H = 1080;

const canvas   = document.getElementById("main");
const video    = document.getElementById("webcam");
const overlay  = document.getElementById("overlay");
const startBtn = document.getElementById("startBtn");
const status   = document.getElementById("status");

let running = false;
let fpsFrames = 0, fpsLast = performance.now(), fpsVal = 0;

// ----- bootstrap -----

startBtn.addEventListener("click", async () => {
  startBtn.textContent = "Loading model\u2026";
  startBtn.disabled = true;

  try {
    await initPose(video);
    await startCamera();
    renderer.init(canvas);
    overlay.style.display = "none";
    running = true;
    requestAnimationFrame(loop);
  } catch (e) {
    startBtn.textContent = "Error \u2013 see console";
    console.error(e);
  }
});

// ----- render loop -----

function loop(timestamp) {
  if (!running) return;

  detectFrame(timestamp);

  if (consumeNewPose()) {
    const prev = getPrev();
    const cur  = getCur();
    const { angles, mags, kpVelocities } = buildFlowField(prev, cur, W, H);
    renderer.uploadFlowField(angles, mags);
    renderer.uploadKeypoints(cur, W, H);
    renderer.uploadVelocities(kpVelocities);
  }

  renderer.frame();

  // FPS counter
  fpsFrames++;
  const now = performance.now();
  if (now - fpsLast > 1000) {
    fpsVal = fpsFrames;
    fpsFrames = 0;
    fpsLast = now;
    status.textContent = `${fpsVal} fps`;
  }

  requestAnimationFrame(loop);
}
