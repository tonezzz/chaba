const LIVE_DATA_URL = null; // no public live endpoint yet; set to e.g. "http://tony-omen.local:11023/data/mcp-savings.json" if one is added

async function loadReport() {
  const status = document.getElementById('status');
  const report = document.getElementById('report');
  const live = document.getElementById('live-note');
  status.textContent = 'Loading...';
  report.innerHTML = '';
  if (live) live.textContent = '';

  let data;
  if (LIVE_DATA_URL) {
    try {
      const res = await fetch(LIVE_DATA_URL + '?t=' + Date.now(), { mode: 'cors' });
      if (res.ok) data = await res.json();
      else throw new Error('live endpoint unavailable');
      if (live) live.textContent = 'Live data from tony-omen';
    } catch (e) {
      console.warn('Live data failed, falling back to cached snapshot:', e);
      if (live) live.textContent = 'Live data unavailable; showing cached snapshot.';
    }
  }

  try {
    if (!data) {
      const res = await fetch('data/mcp-savings.json?t=' + Date.now());
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
      data = await res.json();
    }
    if (!data.ok) throw new Error(data.error || 'report not ok');
    renderReport(data);
    const generated = data.generated ? new Date(data.generated).toLocaleString() : 'unknown';
    status.innerHTML = `Snapshot: <span class="font-mono">${generated}</span>`;
  } catch (e) {
    status.textContent = 'Error';
    report.innerHTML = `<p style="color:#dc2626">Failed to load report: ${escapeHtml(e.message)}</p>`;
  }
}

function renderReport(data) {
  const report = document.getElementById('report');
  let html = '';

  const hosts = Object.entries(data.hosts).sort(([a], [b]) => a.localeCompare(b));
  for (const [host, hdata] of hosts) {
    html += `<h2 class="text-xl font-semibold mt-8 mb-2">${host}</h2>`;
    html += '<table><thead><tr>';
    html += '<th>Command</th>';
    html += '<th>Raw chars</th>';
    html += '<th>Compact chars</th>';
    html += '<th>Saved chars</th>';
    html += '<th>Char %</th>';
    html += '<th>Word %</th>';
    html += '</tr></thead><tbody>';

    const commands = Object.values(hdata.commands).sort((a, b) =>
      (b.savings_pct_chars || 0) - (a.savings_pct_chars || 0)
    );
    for (const c of commands) {
      const negative = (c.savings_pct_chars || 0) < 0 ? 'negative' : '';
      html += `<tr>
        <td>${escapeHtml(c.command)}</td>
        <td>${c.raw_chars}</td>
        <td>${c.compact_chars}</td>
        <td>${c.saved_chars}</td>
        <td class="${negative}">${(c.savings_pct_chars || 0).toFixed(1)}</td>
        <td>${(c.savings_pct || 0).toFixed(1)}</td>
      </tr>`;
    }
    html += '</tbody></table>';
    html += `<p class="totals text-sm"><strong>${host} totals</strong>: `;
    html += `raw=${hdata.raw_chars}, compact=${hdata.compact_chars}, saved=${hdata.saved_chars} `;
    html += `(${hdata.saved_chars ? ((hdata.saved_chars / hdata.raw_chars) * 100).toFixed(1) : '0.0'}%)</p>`;
  }

  html += `<div class="mt-8 p-4 rounded" style="background: #f3f4f6;">`;
  html += `<p class="font-semibold">Overall totals</p>`;
  html += `<p>raw=${data.total_raw_chars}, compact=${data.total_compact_chars}, saved=${data.total_saved_chars} `;
  html += `(${data.total_savings_pct.toFixed ? data.total_savings_pct.toFixed(1) : data.total_savings_pct}%)</p>`;
  html += `</div>`;

  report.innerHTML = html;
}

function escapeHtml(str) {
  return (str ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

document.getElementById('refresh').addEventListener('click', loadReport);
loadReport();
