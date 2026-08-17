const LIVE_DATA_URL = "/api/mcp-savings.php"; // same-origin PHP proxy to tony-omen
const TABLE_DATA_URL = "/api/mcp-table.php"; // same-origin proxy for /mcp-table.json
const FETCH_TIMEOUT = 8000; // proxy + mcp_report cache may take a few seconds

function renderSkeleton() {
  const report = document.getElementById('report');
  report.innerHTML = `
    <div class="p-4 rounded mb-4" style="background: #f9fafb;">
      <p class="text-gray-500 text-sm">Loading report...</p>
    </div>
    <div id="skeleton-tables"></div>
  `;
  const skel = document.getElementById('skeleton-tables');
  const hosts = ['tony_omen', 'tony_dell'];
  let html = '';
  for (const host of hosts) {
    html += `<h2 class="text-xl font-semibold mt-8 mb-2">${host}</h2>`;
    html += '<table><thead><tr>';
    ['Command', 'Raw chars', 'Compact chars', 'Saved chars', 'Char %', 'Word %'].forEach(h => {
      html += `<th>${h}</th>`;
    });
    html += '</tr></thead><tbody>';
    for (let i = 0; i < 8; i++) {
      html += '<tr><td class="text-gray-400">...</td><td class="text-gray-400">-</td><td class="text-gray-400">-</td><td class="text-gray-400">-</td><td class="text-gray-400">-</td><td class="text-gray-400">-</td></tr>';
    }
    html += '</tbody></table>';
  }
  skel.innerHTML = html;
}

async function fetchWithTimeout(url, options = {}, timeout = FETCH_TIMEOUT) {
  const controller = new AbortController();
  const id = setTimeout(() => controller.abort(), timeout);
  try {
    const res = await fetch(url, { ...options, signal: controller.signal });
    clearTimeout(id);
    return res;
  } catch (e) {
    clearTimeout(id);
    throw e;
  }
}

async function loadReport(forceRefresh = false) {
  const status = document.getElementById('status');
  const report = document.getElementById('report');
  const live = document.getElementById('live-note');
  status.textContent = 'Loading...';
  renderSkeleton();
  if (live) live.textContent = '';

  let data;
  if (LIVE_DATA_URL) {
    try {
      const res = await fetchWithTimeout(LIVE_DATA_URL + '?t=' + Date.now() + (forceRefresh ? '&refresh=1' : ''), { mode: 'cors' });
      if (res.ok) data = await res.json();
      else throw new Error('live endpoint unavailable');
      if (live) live.textContent = data.freshness ? 'Live data from tony-omen' : 'Live data unavailable; showing cached snapshot.';
    } catch (e) {
      console.warn('Live data failed, falling back to cached snapshot:', e);
      if (live) live.textContent = 'Live data unavailable; showing cached snapshot.';
    }
  } else if (live) {
    live.textContent = 'Live endpoint disabled until HTTPS/proxy is configured.';
  }

  try {
    if (!data) {
      const res = await fetchWithTimeout('data/mcp-savings.json?t=' + Date.now());
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
      data = await res.json();
    }
    if (!data.ok) throw new Error(data.error || 'report not ok');
    renderReport(data);
    const generated = data.generated ? new Date(data.generated).toLocaleString() : 'unknown';
    const source = data.freshness ? 'Live' : 'Snapshot';
    status.innerHTML = `${source}: <span class="font-mono">${generated}</span>`;
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
      html += `<tr data-host="${host}" data-command="${c.command}">
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

async function loadTable(host, command) {
  const detail = document.getElementById('detail');
  const title = document.getElementById('detail-title');
  const table = document.getElementById('detail-table');
  const status = document.getElementById('detail-status');

  detail.classList.remove('hidden');
  title.textContent = `${host} — ${command}`;
  table.innerHTML = '<p class="text-gray-500 text-sm">Loading table...</p>';
  status.textContent = '';

  try {
    const res = await fetchWithTimeout(`${TABLE_DATA_URL}?host=${encodeURIComponent(host)}&command=${encodeURIComponent(command)}&t=` + Date.now());
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    const data = await res.json();
    if (!data.ok) throw new Error(data.error || 'table not ok');
    renderDetailTable(data);
    status.textContent = 'Live data from tony-dell';
  } catch (e) {
    table.innerHTML = `<p style="color:#dc2626">Failed to load table: ${escapeHtml(e.message)}</p>`;
    status.textContent = 'Live table unavailable';
  }
}

function renderDetailTable(data) {
  const table = document.getElementById('detail-table');
  if (!data.headers || !data.rows || data.rows.length === 0) {
    table.innerHTML = '<p class="text-gray-500 text-sm">No table rows returned.</p>';
    return;
  }

  let html = '<table><thead><tr>';
  for (const h of data.headers) {
    html += `<th>${escapeHtml(h)}</th>`;
  }
  html += '</tr></thead><tbody>';
  for (const row of data.rows) {
    html += '<tr>';
    for (const cell of row) {
      html += `<td>${escapeHtml(cell)}</td>`;
    }
    html += '</tr>';
  }
  html += '</tbody></table>';
  table.innerHTML = html;
}

document.getElementById('report').addEventListener('click', (e) => {
  const row = e.target.closest('tr[data-host]');
  if (!row) return;
  const host = row.getAttribute('data-host');
  const command = row.getAttribute('data-command');
  if (host && command) loadTable(host, command);
});

document.getElementById('detail-close').addEventListener('click', () => {
  document.getElementById('detail').classList.add('hidden');
});

document.getElementById('refresh').addEventListener('click', () => loadReport(true));
renderSkeleton();
loadReport();
