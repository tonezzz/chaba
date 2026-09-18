// WebGL2 particle renderer — sunset-gradient palette on cream background.
//
// Visual model:
//   - Background is warm cream ("paper").
//   - Particles paint marks whose color comes from a vertical sunset
//     gradient:  head (top) = dusty blue  →  feet (bottom) = burnt orange.
//   - Slow/soft movement → bright, barely-visible wisps (close to cream).
//   - Fast/aggressive movement → bold, saturated marks + dust uplift.
//   - Trails fade back toward cream each frame for a watercolour feel.
//
// Public API:
//   init(canvas)
//   uploadFlowField(angles, mags)
//   uploadKeypoints(landmarks, W, H)
//   uploadVelocities(kpVelocities)
//   frame()

import { GRID } from "./flowfield.js";
import { BG }   from "./colors.js";

const W = 1920, H = 1080;
const PTEX = 256;
const N_PARTICLES = PTEX * PTEX;
const BLOOM_DIV = 4;
const BW = W / BLOOM_DIV, BH = H / BLOOM_DIV;
const FADE = 0.978;

let gl;

let particleTex = [], particleFBO = [];
let trailTex    = [], trailFBO    = [];
let bloomTex    = [], bloomFBO    = [];
let flowAngleTex, flowMagTex;

let progUpdate, progDraw, progFade, progBlurH, progBlurV, progComposite;
let quadVAO, particleVAO;
let ppIdx = 0;

let kpUniform  = new Float32Array(17 * 2);
let kpVelUniform = new Float32Array(17);

// -----------------------------------------------------------------------
// GLSL sources
// -----------------------------------------------------------------------

const FULLSCREEN_VS = `#version 300 es
in vec2 a_pos;
out vec2 v_uv;
void main(){ v_uv = a_pos*.5+.5; gl_Position = vec4(a_pos,0,1); }`;

// --- Particle state update (ping-pong) ---
const UPDATE_FS = `#version 300 es
precision highp float;
uniform sampler2D u_state;
uniform sampler2D u_angles;
uniform sampler2D u_mags;
uniform vec2 u_size;
uniform float u_seed;
in vec2 v_uv;
out vec4 fragColor;

float rand(vec2 co){
  return fract(sin(dot(co,vec2(12.9898,78.233)))*43758.5453);
}

void main(){
  vec4 s = texture(u_state, v_uv);
  vec2 pos = s.xy;
  float age = s.z;

  vec2 fuv   = pos / u_size;
  float angle = texture(u_angles, fuv).r;
  float mag   = texture(u_mags, fuv).r;
  float speed = clamp(mag, 0.4, 4.5);

  // Organic micro-jitter
  float jx = (rand(v_uv + u_seed + 0.3) - 0.5) * 0.6;
  float jy = (rand(v_uv + u_seed + 0.4) - 0.5) * 0.6;

  pos += vec2(cos(angle), sin(angle)) * speed + vec2(jx, jy);
  pos  = mod(pos, u_size);
  age += 1.0;

  float r = rand(v_uv + u_seed);
  if(r < 0.004){
    pos = vec2(rand(v_uv+u_seed+0.1), rand(v_uv+u_seed+0.2)) * u_size;
    age = 0.0;
  }
  fragColor = vec4(pos, age, 1.0);
}`;

// --- Particle draw (vertex) ---
const DRAW_VS = `#version 300 es
precision highp float;
uniform sampler2D u_state;
uniform vec2  u_size;
uniform int   u_texW;
uniform vec2  u_kp[17];
uniform float u_kpVel[17];

out vec2  v_pos;
out float v_power;
out float v_nearestY;

void main(){
  int id = gl_VertexID;
  int y  = id / u_texW;
  int x  = id - y * u_texW;
  vec2 uv = (vec2(x,y)+0.5) / float(u_texW);
  vec4 s  = texture(u_state, uv);
  v_pos   = s.xy;

  // Nearest keypoint → colour + intensity
  float bestD = 1e9;
  int   bestI = 0;
  for(int i=0;i<17;i++){
    float d = distance(v_pos, u_kp[i]);
    if(d < bestD){ bestD = d; bestI = i; }
  }

  v_power    = smoothstep(0.0, 0.07, u_kpVel[bestI]);
  v_nearestY = u_kp[bestI].y / u_size.y;

  vec2 ndc = (s.xy / u_size) * 2.0 - 1.0;
  gl_Position  = vec4(ndc.x, -ndc.y, 0, 1);
  gl_PointSize = mix(1.5, 3.5, v_power);
}`;

// --- Particle draw (fragment) ---
const DRAW_FS = `#version 300 es
precision highp float;
uniform vec3 u_bg;
in vec2  v_pos;
in float v_power;
in float v_nearestY;
out vec4 fragColor;

vec3 sunset(float y){
  vec3 c0 = vec3(0.42, 0.51, 0.75);   // dusty blue
  vec3 c1 = vec3(0.62, 0.67, 0.74);   // soft blue-grey
  vec3 c2 = vec3(0.91, 0.84, 0.75);   // warm cream
  vec3 c3 = vec3(0.82, 0.50, 0.25);   // warm orange
  vec3 c4 = vec3(0.72, 0.25, 0.12);   // burnt orange
  if(y < 0.25) return mix(c0, c1, y / 0.25);
  if(y < 0.45) return mix(c1, c2, (y - 0.25) / 0.20);
  if(y < 0.70) return mix(c2, c3, (y - 0.45) / 0.25);
  return mix(c3, c4, clamp((y - 0.70) / 0.30, 0.0, 1.0));
}

void main(){
  // Soft circular falloff
  vec2 pc = gl_PointCoord * 2.0 - 1.0;
  float r2 = dot(pc, pc);
  if(r2 > 1.0) discard;
  float soft = (1.0 - r2) * (1.0 - r2);

  vec3 grad = sunset(v_nearestY);

  // Slow → lighter gradient;  Fast → deep saturated gradient
  vec3 col   = mix(grad * 0.82, grad * 0.4, v_power);
  float alpha = mix(0.025, 0.12, v_power) * soft;

  fragColor = vec4(col, alpha);
}`;

// --- Trail fade toward cream ---
const FADE_FS = `#version 300 es
precision highp float;
uniform sampler2D u_tex;
uniform float u_fade;
uniform vec3  u_bg;
in vec2 v_uv;
out vec4 fragColor;
void main(){
  vec3 col = texture(u_tex, v_uv).rgb;
  fragColor = vec4(mix(u_bg, col, u_fade), 1.0);
}`;

// --- Bloom blur (separable Gaussian, 13-tap) ---
const BLUR_FS = () => `#version 300 es
precision highp float;
uniform sampler2D u_tex;
uniform vec2 u_dir;
in vec2 v_uv;
out vec4 fragColor;
void main(){
  vec4 sum = vec4(0);
  float w[7] = float[](0.1964825501511404,0.2969069646728344,0.2969069646728344,
                        0.09447039785044732,0.09447039785044732,0.010381362401148057,0.010381362401148057);
  float o[7] = float[](0.0,1.3846153846,1.3846153846,3.2307692308,3.2307692308,5.076923077,5.076923077);
  float sign[7] = float[](0.0, 1.0,-1.0, 1.0,-1.0, 1.0,-1.0);
  for(int i=0;i<7;i++){
    sum += texture(u_tex, v_uv + u_dir * o[i] * sign[i]) * w[i];
  }
  fragColor = sum;
}`;

// --- Final composite: 3D ball-surface with Perlin-noise gradient ---
const COMPOSITE_FS = `#version 300 es
precision highp float;
uniform sampler2D u_trail;
uniform sampler2D u_bloom;
uniform vec2  u_res;
uniform vec3  u_bg;
uniform float u_time;
in vec2 v_uv;
out vec4 fragColor;

const float SPACING = 6.0;
const float RADIUS  = 2.6;

// ---- hashing helpers ----

vec2 hash2(vec2 p){
  p = vec2(dot(p,vec2(127.1,311.7)), dot(p,vec2(269.5,183.3)));
  return fract(sin(p)*43758.5453) - 0.5;
}

vec3 hash3(vec3 p){
  p = vec3(dot(p,vec3(127.1,311.7,74.7)),
           dot(p,vec3(269.5,183.3,246.1)),
           dot(p,vec3(113.5,271.9,124.6)));
  return -1.0 + 2.0 * fract(sin(p) * 43758.5453);
}

// ---- 3-D gradient noise ----

float gnoise(vec3 p){
  vec3 i = floor(p), f = fract(p);
  vec3 u = f*f*(3.0-2.0*f);
  return mix(
    mix(mix(dot(hash3(i),              f),
            dot(hash3(i+vec3(1,0,0)),  f-vec3(1,0,0)), u.x),
        mix(dot(hash3(i+vec3(0,1,0)),  f-vec3(0,1,0)),
            dot(hash3(i+vec3(1,1,0)),  f-vec3(1,1,0)), u.x), u.y),
    mix(mix(dot(hash3(i+vec3(0,0,1)),  f-vec3(0,0,1)),
            dot(hash3(i+vec3(1,0,1)),  f-vec3(1,0,1)), u.x),
        mix(dot(hash3(i+vec3(0,1,1)),  f-vec3(0,1,1)),
            dot(hash3(i+vec3(1,1,1)),  f-vec3(1,1,1)), u.x), u.y), u.z);
}

float fbm(vec3 p){
  return gnoise(p)*0.65 + gnoise(p*2.0+3.3)*0.35;
}

// ---- sunset gradient ----

vec3 sunset(float y){
  vec3 c0 = vec3(0.42,0.51,0.75);
  vec3 c1 = vec3(0.62,0.67,0.74);
  vec3 c2 = vec3(0.91,0.84,0.75);
  vec3 c3 = vec3(0.82,0.50,0.25);
  vec3 c4 = vec3(0.72,0.25,0.12);
  if(y<0.25) return mix(c0,c1,y/0.25);
  if(y<0.45) return mix(c1,c2,(y-0.25)/0.20);
  if(y<0.70) return mix(c2,c3,(y-0.45)/0.25);
  return mix(c3,c4,clamp((y-0.70)/0.30,0.0,1.0));
}

// ---- main ----

void main(){
  vec2 px   = v_uv * u_res;
  vec2 cell = floor(px / SPACING);

  // Nearest dot centre (3x3 search)
  float bestD = 1e9;
  vec2  bestC = vec2(0);
  for(int dy=-1; dy<=1; dy++){
    for(int dx=-1; dx<=1; dx++){
      vec2 nc  = cell + vec2(float(dx), float(dy));
      vec2 off = hash2(nc) * 0.35;
      vec2 ctr = (nc + 0.5 + off) * SPACING;
      float d  = distance(px, ctr);
      if(d < bestD){ bestD = d; bestC = ctr; }
    }
  }

  vec2 duv  = clamp(bestC / u_res, vec2(0), vec2(1));
  vec3 tCol = texture(u_trail, duv).rgb;
  vec3 bCol = texture(u_bloom, duv).rgb;
  vec3 trailMark = mix(tCol, bCol, 0.10);

  // Perlin-noise driven sunset gradient for the entire surface
  float n = fbm(vec3(duv * 7.0, u_time * 0.12)) * 0.5 + 0.5;
  vec3 noiseGrad = sunset(n);

  // How much "ink" the trail has deposited (deviation from cream)
  float ink = clamp(length(u_bg - trailMark) * 10.0, 0.0, 1.0);

  // Base: noise gradient everywhere; trail marks paint over it
  vec3 col = mix(noiseGrad, trailMark, ink * 0.9);

  // Per-dot micro-variation
  col += hash2(cell + 42.0).x * 0.02;

  if(bestD < RADIUS){
    vec2  n2 = (px - bestC) / RADIUS;
    float nz = sqrt(max(0.0, 1.0 - dot(n2, n2)));
    vec3  N  = normalize(vec3(n2, nz));

    vec3  L    = normalize(vec3(-0.4, -0.5, 0.75));
    float diff = max(0.0, dot(N, L));

    vec3  H    = normalize(L + vec3(0,0,1));
    float spec = pow(max(0.0, dot(N, H)), 28.0);

    vec3 lit = col * (0.78 + 0.22 * diff) + spec * 0.07;
    fragColor = vec4(lit, 1.0);
  } else {
    float g = smoothstep(RADIUS, RADIUS + 1.3, bestD);
    fragColor = vec4(col * (0.60 + 0.25 * g), 1.0);
  }
}`;

// -----------------------------------------------------------------------
// Helpers
// -----------------------------------------------------------------------

function compile(src, type) {
  const s = gl.createShader(type);
  gl.shaderSource(s, src);
  gl.compileShader(s);
  if (!gl.getShaderParameter(s, gl.COMPILE_STATUS))
    throw new Error(gl.getShaderInfoLog(s));
  return s;
}

function link(vs, fs) {
  const p = gl.createProgram();
  gl.attachShader(p, compile(vs, gl.VERTEX_SHADER));
  gl.attachShader(p, compile(fs, gl.FRAGMENT_SHADER));
  gl.linkProgram(p);
  if (!gl.getProgramParameter(p, gl.LINK_STATUS))
    throw new Error(gl.getProgramInfoLog(p));
  return p;
}

function makeTex(w, h, internalFmt, fmt, type, data) {
  const t = gl.createTexture();
  gl.bindTexture(gl.TEXTURE_2D, t);
  gl.texImage2D(gl.TEXTURE_2D, 0, internalFmt, w, h, 0, fmt, type, data);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  return t;
}

function makeFBO(tex) {
  const fb = gl.createFramebuffer();
  gl.bindFramebuffer(gl.FRAMEBUFFER, fb);
  gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, tex, 0);
  return fb;
}

function bindTex(unit, tex) {
  gl.activeTexture(gl.TEXTURE0 + unit);
  gl.bindTexture(gl.TEXTURE_2D, tex);
}

function fullscreenQuad() {
  gl.bindVertexArray(quadVAO);
  gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
}

// -----------------------------------------------------------------------
// Public API
// -----------------------------------------------------------------------

export function init(canvas) {
  gl = canvas.getContext("webgl2", { antialias: false, alpha: false });
  if (!gl) throw new Error("WebGL2 not supported");

  gl.getExtension("EXT_color_buffer_float");
  gl.getExtension("OES_texture_float_linear");

  // Fullscreen quad VAO
  quadVAO = gl.createVertexArray();
  gl.bindVertexArray(quadVAO);
  const qb = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, qb);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1,-1, 1,-1, -1,1, 1,1]), gl.STATIC_DRAW);
  gl.enableVertexAttribArray(0);
  gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);

  particleVAO = gl.createVertexArray();

  // --- Compile programs ---
  progUpdate    = link(FULLSCREEN_VS, UPDATE_FS);
  progDraw      = link(DRAW_VS, DRAW_FS);
  progFade      = link(FULLSCREEN_VS, FADE_FS);
  progBlurH     = link(FULLSCREEN_VS, BLUR_FS());
  progBlurV     = link(FULLSCREEN_VS, BLUR_FS());
  progComposite = link(FULLSCREEN_VS, COMPOSITE_FS);

  // --- Particle state (RGBA32F, 256x256) ---
  const initData = new Float32Array(N_PARTICLES * 4);
  for (let i = 0; i < N_PARTICLES; i++) {
    initData[i * 4]     = Math.random() * W;
    initData[i * 4 + 1] = Math.random() * H;
    initData[i * 4 + 2] = 0;
    initData[i * 4 + 3] = 1;
  }
  for (let i = 0; i < 2; i++) {
    particleTex[i] = makeTex(PTEX, PTEX, gl.RGBA32F, gl.RGBA, gl.FLOAT, i === 0 ? initData : null);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
    particleFBO[i] = makeFBO(particleTex[i]);
  }

  // --- Flow field (R32F, 48x48) ---
  const zeroGrid = new Float32Array(GRID * GRID);
  flowAngleTex = makeTex(GRID, GRID, gl.R32F, gl.RED, gl.FLOAT, zeroGrid);
  flowMagTex   = makeTex(GRID, GRID, gl.R32F, gl.RED, gl.FLOAT, zeroGrid);

  // --- Trail FBOs (RGBA16F for precision, 1920x1080) ---
  for (let i = 0; i < 2; i++) {
    trailTex[i] = makeTex(W, H, gl.RGBA16F, gl.RGBA, gl.HALF_FLOAT, null);
    trailFBO[i] = makeFBO(trailTex[i]);
  }

  // --- Bloom FBOs (RGBA8, quarter-res) ---
  for (let i = 0; i < 2; i++) {
    bloomTex[i] = makeTex(BW, BH, gl.RGBA8, gl.RGBA, gl.UNSIGNED_BYTE, null);
    bloomFBO[i] = makeFBO(bloomTex[i]);
  }

  // --- Clear everything to cream ---
  for (let i = 0; i < 2; i++) {
    gl.bindFramebuffer(gl.FRAMEBUFFER, trailFBO[i]);
    gl.viewport(0, 0, W, H);
    gl.clearColor(BG[0], BG[1], BG[2], 1.0);
    gl.clear(gl.COLOR_BUFFER_BIT);
  }
  for (let i = 0; i < 2; i++) {
    gl.bindFramebuffer(gl.FRAMEBUFFER, bloomFBO[i]);
    gl.viewport(0, 0, BW, BH);
    gl.clearColor(BG[0], BG[1], BG[2], 1.0);
    gl.clear(gl.COLOR_BUFFER_BIT);
  }
  gl.bindFramebuffer(gl.FRAMEBUFFER, null);
}

export function uploadFlowField(fieldAngles, fieldMags) {
  gl.bindTexture(gl.TEXTURE_2D, flowAngleTex);
  gl.texSubImage2D(gl.TEXTURE_2D, 0, 0, 0, GRID, GRID, gl.RED, gl.FLOAT, fieldAngles);
  gl.bindTexture(gl.TEXTURE_2D, flowMagTex);
  gl.texSubImage2D(gl.TEXTURE_2D, 0, 0, 0, GRID, GRID, gl.RED, gl.FLOAT, fieldMags);
}

export function uploadKeypoints(landmarks, cW, cH) {
  for (let i = 0; i < 17; i++) {
    kpUniform[i * 2]     = landmarks[i * 2] * cW;
    kpUniform[i * 2 + 1] = landmarks[i * 2 + 1] * cH;
  }
}

export function uploadVelocities(vel) {
  kpVelUniform.set(vel);
}

let frameCount = 0;

export function frame() {
  const src = ppIdx;
  const dst = 1 - ppIdx;
  frameCount++;

  // --- Pass 1: Update particles ---
  gl.bindFramebuffer(gl.FRAMEBUFFER, particleFBO[dst]);
  gl.viewport(0, 0, PTEX, PTEX);
  gl.useProgram(progUpdate);
  bindTex(0, particleTex[src]);
  bindTex(1, flowAngleTex);
  bindTex(2, flowMagTex);
  gl.uniform1i(gl.getUniformLocation(progUpdate, "u_state"), 0);
  gl.uniform1i(gl.getUniformLocation(progUpdate, "u_angles"), 1);
  gl.uniform1i(gl.getUniformLocation(progUpdate, "u_mags"), 2);
  gl.uniform2f(gl.getUniformLocation(progUpdate, "u_size"), W, H);
  gl.uniform1f(gl.getUniformLocation(progUpdate, "u_seed"), frameCount * 0.01);
  fullscreenQuad();

  // --- Pass 2: Fade trail toward cream ---
  gl.bindFramebuffer(gl.FRAMEBUFFER, trailFBO[dst]);
  gl.viewport(0, 0, W, H);
  gl.useProgram(progFade);
  bindTex(0, trailTex[src]);
  gl.uniform1i(gl.getUniformLocation(progFade, "u_tex"), 0);
  gl.uniform1f(gl.getUniformLocation(progFade, "u_fade"), FADE);
  gl.uniform3f(gl.getUniformLocation(progFade, "u_bg"), BG[0], BG[1], BG[2]);
  gl.disable(gl.BLEND);
  fullscreenQuad();

  // --- Pass 3: Draw particles onto trail with alpha blending ---
  gl.enable(gl.BLEND);
  gl.blendFuncSeparate(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA, gl.ZERO, gl.ONE);

  gl.useProgram(progDraw);
  bindTex(0, particleTex[dst]);
  gl.uniform1i(gl.getUniformLocation(progDraw, "u_state"), 0);
  gl.uniform2f(gl.getUniformLocation(progDraw, "u_size"), W, H);
  gl.uniform1i(gl.getUniformLocation(progDraw, "u_texW"), PTEX);
  gl.uniform3f(gl.getUniformLocation(progDraw, "u_bg"), BG[0], BG[1], BG[2]);

  gl.uniform2fv(gl.getUniformLocation(progDraw, "u_kp[0]"),    kpUniform);
  gl.uniform1fv(gl.getUniformLocation(progDraw, "u_kpVel[0]"), kpVelUniform);

  gl.bindVertexArray(particleVAO);
  gl.drawArrays(gl.POINTS, 0, N_PARTICLES);
  gl.disable(gl.BLEND);

  // --- Pass 4: Bloom (ink-spread) ---
  gl.bindFramebuffer(gl.FRAMEBUFFER, bloomFBO[0]);
  gl.viewport(0, 0, BW, BH);
  gl.useProgram(progFade);
  bindTex(0, trailTex[dst]);
  gl.uniform1i(gl.getUniformLocation(progFade, "u_tex"), 0);
  gl.uniform1f(gl.getUniformLocation(progFade, "u_fade"), 1.0);
  gl.uniform3f(gl.getUniformLocation(progFade, "u_bg"), BG[0], BG[1], BG[2]);
  fullscreenQuad();

  gl.bindFramebuffer(gl.FRAMEBUFFER, bloomFBO[1]);
  gl.useProgram(progBlurH);
  bindTex(0, bloomTex[0]);
  gl.uniform1i(gl.getUniformLocation(progBlurH, "u_tex"), 0);
  gl.uniform2f(gl.getUniformLocation(progBlurH, "u_dir"), 1.0 / BW, 0);
  fullscreenQuad();

  gl.bindFramebuffer(gl.FRAMEBUFFER, bloomFBO[0]);
  gl.useProgram(progBlurV);
  bindTex(0, bloomTex[1]);
  gl.uniform1i(gl.getUniformLocation(progBlurV, "u_tex"), 0);
  gl.uniform2f(gl.getUniformLocation(progBlurV, "u_dir"), 0, 1.0 / BH);
  fullscreenQuad();

  // --- Pass 5: Composite to screen ---
  gl.bindFramebuffer(gl.FRAMEBUFFER, null);
  gl.viewport(0, 0, W, H);
  gl.useProgram(progComposite);
  bindTex(0, trailTex[dst]);
  bindTex(1, bloomTex[0]);
  gl.uniform1i(gl.getUniformLocation(progComposite, "u_trail"), 0);
  gl.uniform1i(gl.getUniformLocation(progComposite, "u_bloom"), 1);
  gl.uniform2f(gl.getUniformLocation(progComposite, "u_res"), W, H);
  gl.uniform3f(gl.getUniformLocation(progComposite, "u_bg"), BG[0], BG[1], BG[2]);
  gl.uniform1f(gl.getUniformLocation(progComposite, "u_time"), frameCount * 0.016);
  fullscreenQuad();

  ppIdx = dst;
}
