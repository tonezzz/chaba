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

async function fetchJSON(path) {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`Cannot load ${path}: ${res.status}`);
  return res.json();
}

function trace(name, x, y, color, dash = 'solid') {
  return { name, x, y, type: 'scatter', mode: 'lines', line: { color, dash, width: 1.5 } };
}

function plot(id, data, layout, config) {
  Plotly.newPlot(id, data, layout, config || { displayModeBar: false, responsive: true });
}

function renderPriceLevels(aligned) {
  const dates = aligned.map(r => r.date);
  const normalize = (arr) => {
    const mean = arr.reduce((a, b) => a + b, 0) / arr.length;
    return arr.map(v => ((v / mean) - 1) * 100);
  };
  const xau = aligned.map(r => r.xau);
  const thb = aligned.map(r => r.thb);
  const usd = aligned.map(r => r.usd);
  const data = [
    trace('XAU/USD', dates, normalize(xau), '#d4af37'),
    trace('USD/THB', dates, normalize(thb), '#0d6efd'),
    trace('USD/EUR', dates, normalize(usd), '#dc3545'),
  ];
  plot('price-levels', data, {
    title: 'Normalized price levels (% deviation from mean)',
    xaxis: { title: 'Date' },
    yaxis: { title: '% from mean' },
    height: 400,
    hovermode: 'x unified',
  });
}

function renderReturns(rets) {
  const dates = rets.map(r => r.date);
  const data = [
    trace('XAU return', dates, rets.map(r => r.xau_ret), '#d4af37'),
    trace('THB return', dates, rets.map(r => r.thb_ret), '#0d6efd'),
    trace('USD return', dates, rets.map(r => r.usd_ret), '#dc3545'),
  ];
  plot('returns', data, {
    title: 'Daily log returns',
    xaxis: { title: 'Date' },
    yaxis: { title: 'Log return' },
    height: 400,
    hovermode: 'x unified',
  });
}

function renderStrategyEquity(equity) {
  if (!equity || equity.length === 0) {
    document.getElementById('strategy-equity').innerHTML = '<p class="muted">No equity data. Run <code>trended.py</code> or <code>walkforward.py</code> first.</p>';
    return;
  }
  const dates = equity.map(r => r.date);
  const data = [
    trace('Strategy equity', dates, equity.map(r => r.strategy_equity), '#0d6efd'),
    trace('Buy-and-hold XAU', dates, equity.map(r => r.buyhold_equity), '#d4af37'),
  ];
  plot('strategy-equity', data, {
    title: 'Cumulative equity (log scale)',
    xaxis: { title: 'Date' },
    yaxis: { title: 'Cumulative return', type: 'log' },
    height: 400,
    hovermode: 'x unified',
  });
}

function renderCrossCorr(results) {
  if (!results || !results.cross_correlation_peak || !results.cross_correlation_peak.all_lags) {
    document.getElementById('cross-corr').innerHTML = '<p class="muted">No cross-correlation data. Run <code>analyze.py</code>.</p>';
    return;
  }
  const lags = Object.keys(results.cross_correlation_peak.all_lags).map(Number).sort((a, b) => a - b);
  const corrs = lags.map(l => results.cross_correlation_peak.all_lags[l.toString()]);
  const colors = corrs.map(v => v >= 0 ? '#198754' : '#dc3545');
  plot('cross-corr', [
    { x: lags.map(String), y: corrs, type: 'bar', marker: { color: colors } }
  ], {
    title: 'XAU vs THB return cross-correlation',
    xaxis: { title: 'Lag' },
    yaxis: { title: 'Correlation' },
    height: 320,
    shapes: [{ type: 'line', x0: -10, x1: 10, y0: 0, y1: 0, line: { color: '#000', width: 1 } }],
  });
}

function renderIRF(results) {
  if (!results || !results.impulse_response_xau) {
    document.getElementById('irf').innerHTML = '<p class="muted">No impulse-response data. Run <code>analyze.py</code>.</p>';
    return;
  }
  const steps = Array.from({ length: 10 }, (_, i) => i);
  const traces = [];
  for (const [name, vals] of Object.entries(results.impulse_response_xau)) {
    const label = name.replace('xau_response_to_', '').replace('_ret', '');
    traces.push(trace(label, steps, vals, label === 'thb' ? '#0d6efd' : '#dc3545'));
  }
  plot('irf', traces, {
    title: 'XAU/USD return impulse response',
    xaxis: { title: 'Step (days)' },
    yaxis: { title: 'Response' },
    height: 320,
    hovermode: 'x unified',
  });
}

function populateText(results, aligned) {
  if (results) {
    document.getElementById('n-obs').textContent = results.observations.toLocaleString();
    document.getElementById('range-dates').textContent = results.date_range.join(' → ');
    document.getElementById('results-pre').textContent = JSON.stringify(results, null, 2);
  } else if (aligned) {
    document.getElementById('n-obs').textContent = aligned.length.toLocaleString();
    document.getElementById('range-dates').textContent = `${aligned[0].date} → ${aligned[aligned.length - 1].date}`;
  }
}

async function init() {
  const status = document.getElementById('status');
  try {
    let equity = await fetchCSV('/data/trended_equity.csv').catch(async () => await fetchCSV('/data/walkforward_equity.csv').catch(() => null));
    const [aligned, rets, results] = await Promise.all([
      fetchCSV('/data/aligned.csv').catch(() => null),
      fetchCSV('/data/returns.csv').catch(() => null),
      fetchJSON('/data/results.json').catch(() => null),
    ]);

    if (!aligned && !rets) {
      status.innerHTML = '<span class="error">No data available. Run <code>analyze.py</code> first to generate <code>data/aligned.csv</code> and <code>data/returns.csv</code>.</span>';
      return;
    }

    status.innerHTML = '<span class="muted">Data loaded. Rendering charts...</span>';

    if (aligned) renderPriceLevels(aligned);
    if (rets) renderReturns(rets);
    renderStrategyEquity(equity);
    renderCrossCorr(results);
    renderIRF(results);
    populateText(results, aligned);

    status.innerHTML = '<span class="muted">Ready.</span>';
  } catch (err) {
    status.innerHTML = `<span class="error">${err.message}</span>`;
    console.error(err);
  }
}

init();
