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

function renderDTW() {
  const x1 = Array.from({ length: 40 }, (_, i) => i);
  const y1 = x1.map(i => Math.sin(i * 0.3) + Math.random() * 0.1);
  const y2 = x1.map(i => Math.sin((i + 2) * 0.3) + Math.random() * 0.1);
  plot('idea-dtw', [
    { x: x1, y: y1, mode: 'lines', name: 'Current THB window', line: { color: COLORS.thb } },
    { x: x1, y: y2, mode: 'lines', name: 'Historical neighbor (warped)', line: { color: COLORS.grey, dash: 'dash' } },
  ], {
    title: 'DTW: elastic alignment of two return windows',
    xaxis: { title: 'Time step' },
    yaxis: { title: 'Return' },
    height: 350,
  });
}

function renderDelay() {
  const n = 300;
  const x = [], y = [], z = [];
  for (let i = 0; i < n; i++) {
    const t = i * 0.1;
    const xt = Math.sin(t) + 0.3 * Math.sin(3.1 * t);
    const yt = Math.sin(t + 0.5) + 0.3 * Math.sin(3.1 * t + 0.5);
    const zt = Math.sin(t + 1.0) + 0.3 * Math.sin(3.1 * t + 1.0);
    x.push(xt); y.push(yt); z.push(zt);
  }
  plot('idea-delay', [
    { x, y, z, mode: 'lines', type: 'scatter3d', name: 'THB phase space', line: { color: COLORS.thb, width: 4 } },
  ], {
    title: 'Delay embedding: [thb_t, thb_{t-1}, thb_{t-2}]',
    scene: { xaxis: { title: 'thb_t' }, yaxis: { title: 'thb_{t-1}' }, zaxis: { title: 'thb_{t-2}' } },
    height: 420,
  });
}

function renderSSA() {
  const n = 120;
  const t = Array.from({ length: n }, (_, i) => i);
  const trend = t.map(i => 0.001 * i);
  const osc = t.map(i => 0.02 * Math.sin(i * 0.3));
  const noise = t.map(() => (Math.random() - 0.5) * 0.02);
  const raw = t.map(i => trend[i] + osc[i] + noise[i]);
  const recon = t.map(i => trend[i] + osc[i]);
  plot('idea-ssa', [
    { x: t, y: raw, mode: 'lines', name: 'Raw THB returns', line: { color: COLORS.grey } },
    { x: t, y: recon, mode: 'lines', name: 'SSA reconstructed signal', line: { color: COLORS.thb } },
  ], {
    title: 'SSA: raw series vs reconstructed signal',
    xaxis: { title: 'Time' },
    yaxis: { title: 'Return' },
    height: 350,
  });
}

function renderVAR() {
  const regimes = ['Regime 1', 'Regime 2'];
  const values = [-0.55, -0.25];
  plot('idea-var', [
    { x: regimes, y: values, type: 'bar', marker: { color: [COLORS.thb, COLORS.usd] } },
  ], {
    title: 'THB impulse on XAU by regime',
    xaxis: { title: 'Regime' },
    yaxis: { title: 'Next-day XAU return' },
    height: 350,
  });
}

function renderGraph() {
  const nodes = ['XAU', 'USD/THB', 'USD/EUR'];
  const x = [0, 1, 0.5];
  const y = [1, 1, 0];
  const edges = [{ s: 1, t: 0, w: 0.8 }, { s: 2, t: 0, w: 0.4 }];
  const shapes = [];
  for (const e of edges) {
    const x0 = x[e.s], y0 = y[e.s], x1 = x[e.t], y1 = y[e.t];
    const mx = (x0 + x1) / 2, my = (y0 + y1) / 2;
    shapes.push({ type: 'line', x0, y0, x1, y1, line: { color: 'rgba(13,110,253,' + e.w + ')', width: 2 + e.w * 4 } });
    shapes.push({ type: 'circle', x0: mx - 0.02, y0: my - 0.02, x1: mx + 0.02, y1: my + 0.02, fillcolor: COLORS.thb });
  }
  plot('idea-graph', [
    { x, y, mode: 'text+markers', type: 'scatter', text: nodes, textposition: 'top center', marker: { size: 20, color: COLORS.xau } },
  ], {
    title: 'Rolling directed network: THB/EUR → XAU',
    xaxis: { visible: false, range: [-0.3, 1.3] },
    yaxis: { visible: false, range: [-0.2, 1.2] },
    height: 420,
    shapes,
  });
}

function renderWavelet() {
  const freqs = Array.from({ length: 20 }, (_, i) => i + 1);
  const times = Array.from({ length: 40 }, (_, i) => i);
  const z = freqs.map(f => times.map(t => {
    const v = Math.exp(-Math.pow((t - 20) / 8, 2)) * Math.exp(-Math.pow((f - 5) / 3, 2));
    return v + Math.random() * 0.02;
  }));
  plot('idea-wavelet', [
    { x: times, y: freqs, z, type: 'heatmap', colorscale: 'Viridis', showscale: false },
  ], {
    title: 'Wavelet coherence: time vs frequency',
    xaxis: { title: 'Time' },
    yaxis: { title: 'Frequency band' },
    height: 420,
  });
}

async function fetchCSV(path, column = 'equity') {
  const res = await fetch(path);
  if (!res.ok) return null;
  const lines = (await res.text()).trim().split('\n');
  const headers = lines[0].split(',');
  const idx = headers.indexOf(column);
  const colIdx = idx >= 0 ? idx : headers.length - 1;
  return lines.slice(1).map(line => {
    const parts = line.split(',');
    return { date: parts[0], equity: parseFloat(parts[colIdx]) };
  }).filter(r => !isNaN(r.equity));
}

async function renderEquity() {
  const container = document.getElementById('equity-curves');
  try {
    const [trended, knn, dtw, delay, ssa, rvar, graph, wavelet, graph_knn, graph_knn_vol, graph_knn_silver, graph_knn_vol_silver, graph_knn_thb_xag] = await Promise.all([
      fetchCSV('data/trended_equity.csv', 'equity').catch(() => null),
      fetchCSV('data/trended_knn_equity.csv', 'equity').catch(() => null),
      fetchCSV('data/trended_dtw_equity.csv', 'equity').catch(() => null),
      fetchCSV('data/trended_delay_equity.csv', 'equity').catch(() => null),
      fetchCSV('data/trended_ssa_equity.csv', 'equity').catch(() => null),
      fetchCSV('data/trended_regime_var_equity.csv', 'equity').catch(() => null),
      fetchCSV('data/trended_graph_equity.csv', 'equity').catch(() => null),
      fetchCSV('data/trended_wavelet_equity.csv', 'equity').catch(() => null),
      fetchCSV('data/trended_graph_knn_equity.csv', 'equity').catch(() => null),
      fetchCSV('data/trended_graph_knn_vol_equity.csv', 'equity').catch(() => null),
      fetchCSV('data/trended_graph_knn_silver_equity.csv', 'equity').catch(() => null),
      fetchCSV('data/trended_graph_knn_vol_silver_equity.csv', 'equity').catch(() => null),
      fetchCSV('data/trended_graph_knn_thb_xag_equity.csv', 'equity').catch(() => null),
    ]);
    if (!graph_knn) {
      container.innerHTML = '<p class="muted">Vector-analysis equity data not yet available. Run the backtests first.</p>';
      return;
    }
    const dates = graph_knn.map(r => r.date);
    const traces = [];
    if (trended) {
      traces.push({ x: dates, y: trended.map(r => r.equity), mode: 'lines', name: '2-day THB trend', line: { color: '#0d6efd' } });
    }
    if (knn) {
      traces.push({ x: dates, y: knn.map(r => r.equity), mode: 'lines', name: 'k-NN (K=20)', line: { color: '#198754' } });
    }
    if (dtw) {
      traces.push({ x: dates, y: dtw.map(r => r.equity), mode: 'lines', name: 'DTW (W=10, K=20)', line: { color: '#fd7e14' } });
    }
    if (delay) {
      traces.push({ x: dates, y: delay.map(r => r.equity), mode: 'lines', name: 'Delay k-NN (W=6, K=20)', line: { color: '#6f42c1' } });
    }
    if (ssa) {
      traces.push({ x: dates, y: ssa.map(r => r.equity), mode: 'lines', name: 'SSA (L=20, R=2)', line: { color: '#20c997' } });
    }
    if (rvar) {
      traces.push({ x: dates, y: rvar.map(r => r.equity), mode: 'lines', name: 'Regime VAR (l=2, vol=10)', line: { color: '#e83e8c' } });
    }
    if (graph) {
      traces.push({ x: dates, y: graph.map(r => r.equity), mode: 'lines', name: 'Graph edge filter', line: { color: '#6610f2' } });
    }
    if (wavelet) {
      traces.push({ x: dates, y: wavelet.map(r => r.equity), mode: 'lines', name: 'Wavelet (scales 4,8,16,32)', line: { color: '#0dcaf0' } });
    }
    if (graph_knn) {
      traces.push({ x: dates, y: graph_knn.map(r => r.equity), mode: 'lines', name: 'Graph + k-NN', line: { color: '#d63384' } });
    }
    traces.push({ x: dates, y: graph_knn_vol.map(r => r.equity), mode: 'lines', name: 'Graph + k-NN vol-sized', line: { color: '#000000' } });
    if (graph_knn_silver) {
      traces.push({ x: dates, y: graph_knn_silver.map(r => r.equity), mode: 'lines', name: 'Graph + k-NN + XAG/silver', line: { color: '#C0C0C0' } });
    }
    if (graph_knn_vol_silver) {
      traces.push({ x: dates, y: graph_knn_vol_silver.map(r => r.equity), mode: 'lines', name: 'Graph + k-NN + XAG/silver vol-sized', line: { color: '#FFD700' } });
    }
    if (graph_knn_thb_xag) {
      traces.push({ x: dates, y: graph_knn_thb_xag.map(r => r.equity), mode: 'lines', name: 'Graph + k-NN THB+XAG (best)', line: { color: '#FF0000' } });
    }
    plot('equity-curves', traces, {
      title: 'Vector-analysis results vs baselines (log scale)',
      xaxis: { title: 'Date' },
      yaxis: { title: 'Cumulative return', type: 'log' },
      height: 420,
    });
  } catch (err) {
    container.innerHTML = `<p class="error">${err.message}</p>`;
  }
}

function init() {
  renderDTW();
  renderDelay();
  renderSSA();
  renderVAR();
  renderGraph();
  renderWavelet();
  renderEquity();
}

init();
