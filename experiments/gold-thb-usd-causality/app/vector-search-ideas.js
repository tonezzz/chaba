"use strict";

const COLORS = {
  thb: '#0d6efd',
  xau: '#d4af37',
  usd: '#dc3545',
  green: '#198754',
  red: '#dc3545',
  grey: '#6c757d',
};

function plot(id, data, layout) {
  Plotly.newPlot(id, data, layout, { displayModeBar: false, responsive: true });
}

function renderKNN() {
  // Current window and its 5 nearest neighbors in a 2D projection of the return vector
  const current = { x: 0.0, y: 0.5, label: 'Current window' };
  const neighbors = [
    { x: 0.05, y: 0.45, r: 0.02 },
    { x: -0.02, y: 0.55, r: 0.03 },
    { x: 0.08, y: 0.42, r: 0.02 },
    { x: -0.05, y: 0.58, r: 0.04 },
    { x: 0.03, y: 0.48, r: 0.03 },
  ];
  const farPoints = Array.from({ length: 30 }, () => ({
    x: (Math.random() - 0.5) * 2.0,
    y: (Math.random() - 0.5) * 2.0,
  }));

  plot('idea-knn', [
    {
      x: farPoints.map(p => p.x),
      y: farPoints.map(p => p.y),
      mode: 'markers',
      type: 'scatter',
      name: 'Historical windows',
      marker: { color: '#d1d5db', size: 6 },
    },
    {
      x: neighbors.map(n => n.x),
      y: neighbors.map(n => n.y),
      mode: 'markers',
      type: 'scatter',
      name: 'k nearest neighbors',
      marker: { color: COLORS.thb, size: 12, line: { color: '#fff', width: 2 } },
    },
    {
      x: [current.x],
      y: [current.y],
      mode: 'markers',
      type: 'scatter',
      name: current.label,
      marker: { color: COLORS.xau, size: 16, symbol: 'star' },
    },
  ], {
    title: 'Illustrative 2D projection of return windows',
    xaxis: { title: 'Latent dimension 1' },
    yaxis: { title: 'Latent dimension 2' },
    height: 350,
    hovermode: 'closest',
  });
}

function renderPCA() {
  // Two clusters: USD-strength (lower gold) vs USD-weakness (higher gold)
  const clusterA = Array.from({ length: 25 }, () => ({
    x: -0.5 + Math.random() * 0.6,
    y: 0.5 + Math.random() * 0.5,
    color: COLORS.red,
    label: 'USD strength → gold down',
  }));
  const clusterB = Array.from({ length: 25 }, () => ({
    x: 0.2 + Math.random() * 0.6,
    y: -0.5 + Math.random() * 0.5,
    color: COLORS.green,
    label: 'USD weakness → gold up',
  }));
  const points = clusterA.concat(clusterB);

  plot('idea-pca', [
    {
      x: points.map(p => p.x),
      y: points.map(p => p.y),
      mode: 'markers',
      type: 'scatter',
      marker: { color: points.map(p => p.color), size: 8 },
      text: points.map(p => p.label),
    },
    {
      x: [0.0],
      y: [0.0],
      mode: 'markers',
      type: 'scatter',
      name: 'Current window',
      marker: { color: COLORS.xau, size: 16, symbol: 'star' },
    },
  ], {
    title: 'PCA projection of multi-day windows into two regimes',
    xaxis: { title: 'PC1' },
    yaxis: { title: 'PC2' },
    height: 350,
    showlegend: false,
    hovermode: 'closest',
  });
}

function renderWeighted() {
  const labels = ['n1', 'n2', 'n3', 'n4', 'n5'];
  const distances = [0.12, 0.18, 0.25, 0.40, 0.55];
  const xauOutcomes = [-0.012, -0.008, 0.005, -0.004, 0.003];
  const weights = distances.map(d => Math.exp(-d * 5));
  const weighted = xauOutcomes.map((v, i) => v * weights[i]);

  plot('idea-weighted', [
    {
      x: labels,
      y: xauOutcomes,
      name: 'XAU return after neighbor',
      type: 'bar',
      marker: { color: xauOutcomes.map(v => v < 0 ? COLORS.red : COLORS.green) },
    },
    {
      x: labels,
      y: weights,
      name: 'Similarity weight',
      type: 'bar',
      marker: { color: COLORS.thb },
      yaxis: 'y2',
    },
  ], {
    title: 'Weighted forecast from k nearest neighbors',
    xaxis: { title: 'Neighbor (closest → farthest)' },
    yaxis: { title: 'XAU return', side: 'left' },
    yaxis2: { title: 'Weight', overlaying: 'y', side: 'right', showgrid: false },
    barmode: 'group',
    height: 350,
  });
}

function renderAnomaly() {
  const n = 120;
  const dates = Array.from({ length: n }, (_, i) => `day ${i + 1}`);
  const dist = Array.from({ length: n }, () => 0.2 + Math.random() * 0.15);
  // Inject a regime spike
  for (let i = 55; i < 65; i++) dist[i] = 0.7 + Math.random() * 0.2;
  const threshold = Array.from({ length: n }, () => 0.45);

  plot('idea-anomaly', [
    {
      x: dates,
      y: dist,
      mode: 'lines',
      type: 'scatter',
      name: 'k-th nearest-neighbor distance',
      line: { color: COLORS.thb },
    },
    {
      x: dates,
      y: threshold,
      mode: 'lines',
      type: 'scatter',
      name: 'Anomaly threshold',
      line: { color: COLORS.grey, dash: 'dash' },
    },
  ], {
    title: 'Anomaly filter: go flat when distance spikes above threshold',
    xaxis: { title: 'Time' },
    yaxis: { title: 'Distance' },
    height: 350,
    hovermode: 'x unified',
    shapes: [{
      type: 'rect', x0: 55, x1: 65, y0: 0, y1: 1.0,
      fillcolor: 'rgba(220, 53, 69, 0.15)', line: { width: 0 },
    }],
    annotations: [{
      x: 60, y: 0.95, text: 'Unfamiliar regime → flat',
      showarrow: false, font: { color: COLORS.red },
    }],
  });
}

function renderMDDB() {
  const ideas = [
    { text: 'Granger causality on financial time series', score: 0.91 },
    { text: 'Out-of-sample backtesting best practices', score: 0.88 },
    { text: 'Vector search for pattern matching in price data', score: 0.85 },
    { text: 'PCA and UMAP for market regimes', score: 0.79 },
    { text: 'Alpha Vantage and FX data conventions', score: 0.72 },
  ];
  const container = document.getElementById('idea-mddb');
  if (!container) return;
  const ul = document.createElement('ul');
  ideas.forEach(d => {
    const li = document.createElement('li');
    li.innerHTML = `<code style="color:${COLORS.grey}">${d.score.toFixed(2)}</code> — ${d.text}`;
    ul.appendChild(li);
  });
  container.appendChild(ul);
}

async function fetchCSV(path) {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`Cannot load ${path}: ${res.status}`);
  const text = await res.text();
  return new Promise((resolve, reject) => {
    Papa.parse(text, {
      header: true,
      dynamicTyping: true,
      skipEmptyLines: true,
      complete: (r) => resolve(r.data),
      error: reject,
    });
  });
}

function cumsumExp(arr) {
  let s = 0;
  const out = [];
  for (const v of arr) {
    s += v;
    out.push(Math.exp(s));
  }
  return out;
}

async function renderEquity() {
  const container = document.getElementById('equity-curves');
  const tbody = document.getElementById('equity-metrics-body');
  try {
    const [trended, knn, weighted] = await Promise.all([
      fetchCSV('data/trended_equity.csv').catch(() => null),
      fetchCSV('data/trended_knn_equity.csv').catch(() => null),
      fetchCSV('data/trended_weighted_equity.csv').catch(() => null),
    ]);

    if (!trended || !knn || !weighted) {
      container.innerHTML = '<p class="muted">Equity data not yet available on this host. Run the backtests or load from the repo.</p>';
      return;
    }

    const dates = trended.map(r => r.date);
    const bh = trended.map(r => r.buyhold_equity);

    const data = [
      { name: '2-day THB trend', y: trended.map(r => r.strategy_equity), color: '#0d6efd' },
      { name: 'k-NN (K=20)', y: knn.map(r => r.equity), color: '#198754' },
      { name: 'Kernel weighted (γ=0.5)', y: weighted.map(r => r.equity), color: '#dc3545' },
      { name: 'Buy-and-hold XAU', y: bh, color: '#d4af37', dash: 'dash' },
    ];

    plot('equity-curves', data.map(d => ({
      x: dates,
      y: d.y,
      mode: 'lines',
      name: d.name,
      line: { color: d.color, dash: d.dash || 'solid', width: 1.5 },
    })), {
      title: 'Cumulative equity (log scale)',
      xaxis: { title: 'Date' },
      yaxis: { title: 'Cumulative return', type: 'log' },
      height: 420,
      hovermode: 'x unified',
    });

    const metrics = [
      { name: '2-day THB trend', s: 1.46, r: 0.189, dd: -0.213, w: 0.312 },
      { name: 'k-NN (K=20)', s: 1.78, r: 0.207, dd: -0.414, w: 0.297 },
      { name: 'Kernel weighted (γ=0.5)', s: 1.23, r: 0.160, dd: -0.508, w: 0.303 },
      { name: 'Buy-and-hold XAU', s: 0.71, r: 0.114, dd: -0.273, w: 0.532 },
    ];
    tbody.innerHTML = metrics.map(m => `
      <tr style="border-bottom:1px solid #dee2e6;">
        <td>${m.name}</td>
        <td>${m.s.toFixed(2)}</td>
        <td>${(m.r * 100).toFixed(1)}%</td>
        <td>${(m.dd * 100).toFixed(1)}%</td>
        <td>${(m.w * 100).toFixed(1)}%</td>
      </tr>
    `).join('');
  } catch (err) {
    container.innerHTML = `<p class="error">${err.message}</p>`;
    console.error(err);
  }
}

function init() {
  renderKNN();
  renderPCA();
  renderWeighted();
  renderAnomaly();
  renderMDDB();
  renderEquity();
}

init();
