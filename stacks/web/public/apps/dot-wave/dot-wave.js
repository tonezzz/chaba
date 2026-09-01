const canvas = document.getElementById('dotWave');
const ctx = canvas.getContext('2d');

function resize() {
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.floor(window.innerWidth * dpr);
  canvas.height = Math.floor(window.innerHeight * dpr);
  ctx.scale(dpr, dpr);
}
window.addEventListener('resize', resize);
resize();

const colors = [
  { r: 255, g: 30, b: 30 },
  { r: 30, g: 255, b: 30 },
  { r: 30, g: 80, b: 255 }
];

let time = 0;

function draw() {
  const width = window.innerWidth;
  const height = window.innerHeight;
  ctx.globalCompositeOperation = 'source-over';
  ctx.fillStyle = '#000';
  ctx.fillRect(0, 0, width, height);
  ctx.globalCompositeOperation = 'lighter';

  const dx = 16;
  const dy = 16;
  const amplitude = 22;
  const yPeriod = 96;
  const sizeBase = 1.6;
  const sizeAmp = 2.6;
  const xCount = Math.ceil(width / dx) + 6;
  const yCount = Math.ceil(height / dy) + 6;

  for (let j = -3; j < yCount; j++) {
    const y0 = j * dy;
    const waveX = amplitude * Math.sin((y0 / yPeriod) + time * 0.4);
    for (let i = -3; i < xCount; i++) {
      const x0 = i * dx + waveX;
      const phase = (i * 0.55 + j * 0.25) + time;
      const r = sizeBase + sizeAmp * Math.sin(phase);
      const c = colors[((i % 3) + 3) % 3];
      const alpha = 0.35 + 0.65 * Math.max(0, Math.sin(phase));

      ctx.beginPath();
      ctx.arc(x0, y0, Math.max(0.5, r), 0, Math.PI * 2);
      ctx.fillStyle = `rgba(${c.r}, ${c.g}, ${c.b}, ${alpha})`;
      ctx.fill();
    }
  }

  time += 0.025;
  requestAnimationFrame(draw);
}

draw();
