// Classic 3D Perlin noise (Ken Perlin's improved version)
// Returns values in roughly [-1, 1]

const P = new Uint8Array(512);
const GRAD3 = [
  [1,1,0],[-1,1,0],[1,-1,0],[-1,-1,0],
  [1,0,1],[-1,0,1],[1,0,-1],[-1,0,-1],
  [0,1,1],[0,-1,1],[0,1,-1],[0,-1,-1],
];

// Seed the permutation table once
(function initPerm() {
  const perm = new Uint8Array(256);
  for (let i = 0; i < 256; i++) perm[i] = i;
  for (let i = 255; i > 0; i--) {
    const j = (Math.random() * (i + 1)) | 0;
    [perm[i], perm[j]] = [perm[j], perm[i]];
  }
  for (let i = 0; i < 512; i++) P[i] = perm[i & 255];
})();

function fade(t) { return t * t * t * (t * (t * 6 - 15) + 10); }
function lerp(a, b, t) { return a + t * (b - a); }
function dot3(g, x, y, z) { return g[0] * x + g[1] * y + g[2] * z; }

export function noise3D(x, y, z) {
  const X = Math.floor(x) & 255;
  const Y = Math.floor(y) & 255;
  const Z = Math.floor(z) & 255;
  x -= Math.floor(x);
  y -= Math.floor(y);
  z -= Math.floor(z);
  const u = fade(x), v = fade(y), w = fade(z);

  const A  = P[X] + Y,     AA = P[A] + Z,   AB = P[A + 1] + Z;
  const B  = P[X + 1] + Y, BA = P[B] + Z,   BB = P[B + 1] + Z;

  const g = GRAD3;
  return lerp(
    lerp(
      lerp(dot3(g[P[AA]   % 12], x,   y,   z),
           dot3(g[P[BA]   % 12], x-1, y,   z),   u),
      lerp(dot3(g[P[AB]   % 12], x,   y-1, z),
           dot3(g[P[BB]   % 12], x-1, y-1, z),   u), v),
    lerp(
      lerp(dot3(g[P[AA+1] % 12], x,   y,   z-1),
           dot3(g[P[BA+1] % 12], x-1, y,   z-1), u),
      lerp(dot3(g[P[AB+1] % 12], x,   y-1, z-1),
           dot3(g[P[BB+1] % 12], x-1, y-1, z-1), u), v), w);
}
