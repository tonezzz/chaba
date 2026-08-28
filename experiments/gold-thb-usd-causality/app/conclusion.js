const results = [
  { variant: 'THB + XAG graph+k-NN', sharpe: 3.52, ret: '36.8%', vol: '10.4%', dd: '-7.3%', wr: '17.5%', best: true },
  { variant: 'THB + XAG dual edge', sharpe: 3.48, ret: '36.2%', vol: '10.4%', dd: '-7.3%', wr: '16.4%' },
  { variant: 'THB + XAU/XAG spread', sharpe: 3.38, ret: '34.2%', vol: '10.1%', dd: '-11.0%', wr: '15.8%' },
  { variant: 'Vol-sized THB+XAU+XAG', sharpe: 3.46, ret: '39.5%', vol: '11.4%', dd: '-5.4%', wr: '15.6%' },
  { variant: 'THB + XAU baseline', sharpe: 2.77, ret: '22.1%', vol: '8.0%', dd: '-7.5%', wr: '12.4%' },
  { variant: 'THB settle to THB', sharpe: 2.37, ret: '24.2%', vol: '10.2%', dd: '-8.4%', wr: '13.2%' },
  { variant: 'Hold USD + mark THB', sharpe: 2.19, ret: '22.1%', vol: '10.1%', dd: '-7.2%', wr: '51.5%' },
  { variant: 'FX pre-positioning', sharpe: 2.49, ret: '21.4%', vol: '8.6%', dd: '-7.3%', wr: '13.7%' },
  { variant: '2-day THB trend', sharpe: -0.68, ret: '-12.9%', vol: '18.9%', dd: '-76.8%', wr: '29.7%' },
];

async function renderResults() {
  const tbody = document.getElementById('results-body');
  tbody.innerHTML = results.map(r => `<tr class="${r.best ? 'best' : ''}">
    <td>${r.variant}</td>
    <td>${r.sharpe.toFixed(2)}</td>
    <td>${r.ret}</td>
    <td>${r.vol}</td>
    <td>${r.dd}</td>
    <td>${r.wr}</td>
  </tr>`).join('');
}

async function fetchCSV(path) {
  const text = await fetch(path).then(r => r.text());
  const lines = text.trim().split('\n');
  const header = lines[0].split(',');
  const dateIdx = header.indexOf('date');
  const equityIdx = header.indexOf('equity');
  const xauIdx = header.indexOf('xau_t1');
  return lines.slice(1).map(line => {
    const parts = line.split(',');
    return {
      date: parts[dateIdx],
      equity: parseFloat(parts[equityIdx]),
      xau_t1: parseFloat(parts[xauIdx]),
    };
  }).filter(r => !isNaN(r.equity) && !isNaN(r.xau_t1));
}

async function renderEquity() {
  const container = document.getElementById('equity-curve');
  try {
    const data = await fetchCSV('data/trended_graph_knn_thb_xag_equity.csv');
    const dates = data.map(r => r.date);
    const bh = [];
    let eq = 1.0;
    for (const r of data) {
      eq *= Math.exp(r.xau_t1);
      bh.push(eq);
    }
    const traces = [
      { x: dates, y: data.map(r => r.equity), mode: 'lines', name: 'THB + XAG graph+k-NN', line: { color: '#0d6efd' } },
      { x: dates, y: bh, mode: 'lines', name: 'Buy-and-hold XAU (same days)', line: { color: '#6c757d' } },
    ];
    Plotly.newPlot('equity-curve', traces, {
      title: 'Cumulative return (log scale)',
      xaxis: { title: 'Date' },
      yaxis: { title: 'Equity', type: 'log' },
      height: 420,
    });
  } catch (err) {
    container.innerHTML = `<p class="error">${err.message}</p>`;
  }
}

renderResults();
renderEquity();
