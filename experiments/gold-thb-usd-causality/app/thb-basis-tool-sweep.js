const tools = [
  { id: 'thb_xag', label: 'Baseline THB+XAG', file: 'data/trended_graph_knn_thb_xag_equity.csv', results: 'data/trended_graph_knn_thb_xag_results.json', status: 'completed' },
  { id: 'sma_overlay', label: 'SMA overlay', file: 'data/trended_sma_overlay_equity.csv', results: 'data/trended_sma_overlay_results.json', status: 'completed' },
  { id: 'ema_overlay', label: 'EMA overlay', file: 'data/trended_ema_overlay_equity.csv', results: 'data/trended_ema_overlay_results.json', status: 'completed' },
  { id: 'rsi_filter', label: 'RSI filter', file: 'data/trended_rsi_filter_equity.csv', results: 'data/trended_rsi_filter_results.json', status: 'completed' },
  { id: 'macd_filter', label: 'MACD filter', file: 'data/trended_macd_filter_equity.csv', results: 'data/trended_macd_filter_results.json', status: 'completed' },
  { id: 'bollinger', label: 'Bollinger Band mean-reversion', file: 'data/trended_bollinger_equity.csv', results: 'data/trended_bollinger_results.json', status: 'completed' },
  { id: 'atr_sizing', label: 'ATR-based sizing (W=7, TV=15%, p=0.005)', file: 'data/trended_atr_sizing_w7_t15_p5_equity.csv', results: 'data/trended_atr_sizing_w7_t15_p5_results.json', best: true, status: 'completed' },
  { id: 'combined', label: 'Combined best', file: 'data/trended_thb_basis_best_equity.csv', results: 'data/trended_thb_basis_best_results.json', status: 'completed' },
];

const tuning = [
  { id: 'w5_t15', label: 'ATR W=5, TV=15%', file: 'data/trended_atr_sizing_w5_t15_equity.csv', results: 'data/trended_atr_sizing_w5_t15_results.json' },
  { id: 'w7_t15', label: 'ATR W=7, TV=15%', file: 'data/trended_atr_sizing_w7_t15_equity.csv', results: 'data/trended_atr_sizing_w7_t15_results.json' },
  { id: 'w7_t15_p5', label: 'ATR W=7, TV=15%, p=0.005', file: 'data/trended_atr_sizing_w7_t15_p5_equity.csv', results: 'data/trended_atr_sizing_w7_t15_p5_results.json', best: true },
  { id: 'w7_t15_k30', label: 'ATR W=7, TV=15%, K=30', file: 'data/trended_atr_sizing_w7_t15_k30_equity.csv', results: 'data/trended_atr_sizing_w7_t15_k30_results.json' },
  { id: 'w10_t15', label: 'ATR W=10, TV=15%', file: 'data/trended_atr_sizing_w10_t15_equity.csv', results: 'data/trended_atr_sizing_w10_t15_results.json' },
  { id: 'w14_t20', label: 'ATR W=14, TV=20%', file: 'data/trended_atr_sizing_equity.csv', results: 'data/trended_atr_sizing_results.json' },
];

const stress = [
  { id: 'tc05', label: 'TC 0.05%', file: 'data/trended_atr_sizing_w7_t15_equity.csv', results: 'data/trended_atr_sizing_w7_t15_results.json' },
  { id: 'tc10', label: 'TC 0.10%', file: 'data/trended_atr_sizing_w7_t15_tc10_equity.csv', results: 'data/trended_atr_sizing_w7_t15_tc10_results.json' },
  { id: 'tc20', label: 'TC 0.20%', file: 'data/trended_atr_sizing_w7_t15_tc20_equity.csv', results: 'data/trended_atr_sizing_w7_t15_tc20_results.json' },
  { id: 'tc50', label: 'TC 0.50%', file: 'data/trended_atr_sizing_w7_t15_tc50_equity.csv', results: 'data/trended_atr_sizing_w7_t15_tc50_results.json' },
];

async function fetchJSON(path) {
  try {
    const res = await fetch(path);
    if (!res.ok) return null;
    return await res.json();
  } catch (e) {
    return null;
  }
}

async function fetchCSV(path) {
  const text = await fetch(path).then(r => r.text());
  const lines = text.trim().split('\n');
  const header = lines[0].split(',');
  const dateIdx = header.indexOf('date');
  const equityIdx = header.indexOf('equity');
  return lines.slice(1).map(line => {
    const parts = line.split(',');
    return { date: parts[dateIdx], equity: parseFloat(parts[equityIdx]) };
  }).filter(r => !isNaN(r.equity));
}

function fmtPct(n) {
  if (n === undefined || n === null) return '-';
  return (n * 100).toFixed(2) + '%';
}

async function renderTable(items, tbodyId, withStatus=false) {
  const tbody = document.getElementById(tbodyId);
  const rows = await Promise.all(items.map(async t => {
    const r = await fetchJSON(t.results);
    let sharpe = '-', ret = '-', vol = '-', dd = '-', wr = '-';
    if (r && r.strategy_metrics) {
      sharpe = r.strategy_metrics.sharpe?.toFixed(2) || '-';
      ret = fmtPct(r.strategy_metrics.annual_return);
      vol = fmtPct(r.strategy_metrics.annual_vol);
      dd = fmtPct(r.strategy_metrics.max_dd);
      wr = fmtPct(r.strategy_metrics.win_rate);
    }
    const status = withStatus ? `<td>${t.status}</td>` : '';
    return `<tr class="${t.best ? 'best' : ''}">
      <td>${t.label}</td>
      <td>${sharpe}</td>
      <td>${ret}</td>
      <td>${vol}</td>
      <td>${dd}</td>
      <td>${wr}</td>
      ${status}
    </tr>`;
  }));
  tbody.innerHTML = rows.join('');
}

async function renderEquity() {
  const traces = [];
  for (const t of tools) {
    const data = await fetchCSV(t.file).catch(() => null);
    if (!data) continue;
    traces.push({
      x: data.map(r => r.date),
      y: data.map(r => r.equity),
      mode: 'lines',
      name: t.label,
      line: { color: t.best ? '#0d6efd' : undefined },
    });
    if (traces.length >= 6) break;
  }
  Plotly.newPlot('equity-curves', traces, {
    title: 'THB-basis tool sweep (log scale)',
    xaxis: { title: 'Date' },
    yaxis: { title: 'Equity', type: 'log' },
    height: 420,
  });
}

renderTable(tools, 'results-body', true);
renderTable(tuning, 'tuning-body');
renderTable(stress, 'stress-body');
renderEquity();
