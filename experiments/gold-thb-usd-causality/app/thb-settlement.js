async function fetchCSV(path, col) {
  const res = await fetch(path);
  if (!res.ok) return null;
  const text = await res.text();
  const lines = text.trim().split('\n');
  if (lines.length < 2) return null;
  const headers = lines[0].split(',');
  const colIdx = headers.indexOf(col);
  if (colIdx === -1) return null;
  return lines.slice(1).map(line => {
    const parts = line.split(',');
    return { date: parts[0], equity: parseFloat(parts[colIdx]) };
  }).filter(r => !isNaN(r.equity));
}

function plot(id, traces, layout) {
  Plotly.newPlot(id, traces, { ...layout, autosize: true }, { responsive: true });
}

async function renderEquity() {
  const container = document.getElementById('equity-curves');
  try {
    const [xau_usd, xau_thb, hold_usd] = await Promise.all([
      fetchCSV('data/trended_graph_knn_silver_equity.csv', 'equity').catch(() => null),
      fetchCSV('data/trended_graph_knn_thb_equity.csv', 'equity').catch(() => null),
      fetchCSV('data/trended_graph_knn_hold_usd_equity.csv', 'equity').catch(() => null),
    ]);
    if (!xau_usd || !xau_thb || !hold_usd) {
      container.innerHTML = '<p class="muted">Equity data not yet available. Run trended_graph_knn_silver.py, trended_graph_knn_thb.py, and trended_graph_knn_hold_usd.py first.</p>';
      return;
    }
    const dates = xau_usd.map(r => r.date);
    const traces = [
      { x: dates, y: xau_usd.map(r => r.equity), mode: 'lines', name: 'XAU/USD silver (ref)', line: { color: '#C0C0C0' } },
      { x: dates, y: hold_usd.map(r => r.equity), mode: 'lines', name: 'XAU/USD position, USD marked to THB', line: { color: '#0d6efd' } },
      { x: dates, y: xau_thb.map(r => r.equity), mode: 'lines', name: 'XAU/THB position (settle THB)', line: { color: '#FFD700' } },
    ];
    plot('equity-curves', traces, {
      title: 'XAU/USD vs XAU/THB settlement (log scale)',
      xaxis: { title: 'Date' },
      yaxis: { title: 'Cumulative return', type: 'log' },
      height: 420,
    });
  } catch (err) {
    container.innerHTML = `<p class="error">${err.message}</p>`;
  }
}

function init() {
  renderEquity();
}

init();
