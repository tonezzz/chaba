// Flow-field builder with velocity tracking and dust physics.
// Runs on the CPU every time new landmarks arrive (~30 fps).
// Output: angles, magnitudes, and per-keypoint velocities.

import { noise3D } from "./perlin.js";

export const GRID = 48;

const SKELETON_POWER = 1.8;
const INFLUENCE_RADIUS = 0.45;
const NOISE_SCALE = 0.12;

const DUST_VEL_THRESHOLD = 0.04;
const DUST_RADIUS = 0.18;

const ANKLES = [15, 16];

let zOff = 0;

const angles        = new Float32Array(GRID * GRID);
const mags           = new Float32Array(GRID * GRID);
const kpVelocities   = new Float32Array(17);

/**
 * @param {Float32Array} prev  interleaved x,y (34 floats), normalised [0,1]
 * @param {Float32Array} cur   same format
 * @param {number} W  canvas width
 * @param {number} H  canvas height
 * @returns {{ angles: Float32Array, mags: Float32Array, kpVelocities: Float32Array }}
 */
export function buildFlowField(prev, cur, W, H) {
  const cellW = W / GRID;
  const cellH = H / GRID;
  const bodyR = Math.max(W, H) * INFLUENCE_RADIUS;
  const dustR = Math.max(W, H) * DUST_RADIUS;

  zOff += 0.006;

  // --- per-keypoint velocity (normalised coords) ---
  for (let k = 0; k < 17; k++) {
    const dx = cur[k * 2]     - prev[k * 2];
    const dy = cur[k * 2 + 1] - prev[k * 2 + 1];
    kpVelocities[k] = Math.sqrt(dx * dx + dy * dy);
  }

  // --- detect ground impacts (ankles moving fast downward) ---
  const impacts = [];
  for (const ai of ANKLES) {
    const vy = (cur[ai * 2 + 1] - prev[ai * 2 + 1]) * H;
    if (kpVelocities[ai] > DUST_VEL_THRESHOLD && vy > 0) {
      impacts.push({
        x: cur[ai * 2] * W,
        y: cur[ai * 2 + 1] * H,
        strength: Math.min(kpVelocities[ai] / DUST_VEL_THRESHOLD, 3.0),
      });
    }
  }

  // --- build field ---
  for (let gy = 0; gy < GRID; gy++) {
    const cy = gy * cellH + cellH * 0.5;
    for (let gx = 0; gx < GRID; gx++) {
      const cx = gx * cellW + cellW * 0.5;
      const idx = gy * GRID + gx;

      let svx = 0, svy = 0, wSum = 0, minD = 1e9;

      for (let k = 0; k < 17; k++) {
        const px = prev[k * 2] * W;
        const py = prev[k * 2 + 1] * H;
        const dx = cx - px;
        const dy = cy - py;
        const d  = Math.sqrt(dx * dx + dy * dy) + 1e-6;
        if (d < minD) minD = d;

        const w   = 1.0 / Math.pow(d, SKELETON_POWER);
        const mvx = (cur[k * 2]     - prev[k * 2])     * W;
        const mvy = (cur[k * 2 + 1] - prev[k * 2 + 1]) * H;
        svx  += w * mvx;
        svy  += w * mvy;
        wSum += w;
      }

      svx /= wSum;
      svy /= wSum;
      let skelAngle = Math.atan2(svy, svx);
      let skelMag   = Math.sqrt(svx * svx + svy * svy);

      // --- dust uplift: push particles upward near impact ---
      let dustBias = 0;
      for (const imp of impacts) {
        const ddx = cx - imp.x;
        const ddy = cy - imp.y;
        const dd  = Math.sqrt(ddx * ddx + ddy * ddy);
        if (dd < dustR) {
          dustBias += (1 - dd / dustR) * imp.strength;
        }
      }
      if (dustBias > 0) {
        const upAngle = -Math.PI * 0.5;
        const blend   = Math.min(dustBias * 0.4, 0.8);
        const bx = (1 - blend) * Math.cos(skelAngle) + blend * Math.cos(upAngle);
        const by = (1 - blend) * Math.sin(skelAngle) + blend * Math.sin(upAngle);
        skelAngle = Math.atan2(by, bx);
        skelMag  += dustBias * 2.5;
      }

      const inf = Math.pow(Math.max(0, Math.min(1, 1 - minD / bodyR)), 0.6);

      const noiseAngle = noise3D(gx * NOISE_SCALE, gy * NOISE_SCALE, zOff) * Math.PI;

      const sx = inf * Math.cos(skelAngle) + (1 - inf) * Math.cos(noiseAngle);
      const sy = inf * Math.sin(skelAngle) + (1 - inf) * Math.sin(noiseAngle);
      angles[idx] = Math.atan2(sy, sx);

      mags[idx] = 0.8 + inf * Math.min(skelMag * 0.5, 6.0);
    }
  }

  return { angles, mags, kpVelocities };
}
