const LIVE_DATA_URL = "/api/mcp-savings.php";
const PREVIOUS_DATA_URL = "/apps/docs/mcp_debug/data/mcp-savings-previous.json";
const TABLE_DATA_URL = "/api/mcp-table.php";
const FETCH_TIMEOUT = 130000;

let currentReportData = null;
let previousReportData = null;
let autoRefreshId = null;
let refreshPollId = null;

function formatNumber(n) {
  if (n == null) return '-';
  if (n >= 1_000_000_000) return (n / 1_000_000_000).toFixed(1) + 'B';
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'k';
  return n.toString();
}

function formatAge(ms) {
  if (ms == null || ms < 0) return 'unknown';
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  if (ms < 3_600_000) return `${(ms / 60_000).toFixed(1)}m`;
  return `${(ms / 3_600_000).toFixed(1)}h`;
}

function escapeHtml(str) {
  return (str ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function fetchWithTimeout(url, options = {}, timeout = FETCH_TIMEOUT) {
  const controller = new AbortController();
  const id = setTimeout(() => controller.abort(), timeout);
  return fetch(url, { ...options, signal: controller.signal })
    .finally(() => clearTimeout(id));
}

function showProgress(text, percent = 0) {
  const el = document.getElementById('progress');
  const fill = document.getElementById('progress-fill');
  const label = document.getElementById('progress-text');
  el.classList.remove('hidden');
  label.textContent = text;
  fill.style.width = percent + '%';
}

function hideProgress() {
  document.getElementById('progress').classList.add('hidden');
}

function setLoading(isLoading) {
  const btn = document.getElementById('refresh');
  const search = document.getElementById('command-search');
  btn.disabled = isLoading;
  search.disabled = isLoading;
  btn.textContent = isLoading ? 'Refreshing...' : 'Refresh';
}

function startRefreshPoll() {
  if (refreshPollId) return;
  showProgress('Waiting for fresh data from tony-dell, polling every 20 seconds...', 30);
  refreshPollId = setInterval(() => loadReport(false, { poll: true }), 20000);
}

function stopRefreshPoll() {
  if (refreshPollId) { clearInterval(refreshPollId); refreshPollId = null; }
}

async function loadReport(forceRefresh = false, { poll = false } = {}) {
  const status = document.getElementById('status');
  const meta = document.getElementById('meta');
  const live = document.getElementById('live-note');
  if (!poll) {
    status.textContent = 'Loading...';
    if (meta) meta.textContent = '';
  }
  if (live) live.textContent = '';
  if (!poll) setLoading(true);
  if (forceRefresh) showProgress('Refresh triggered on tony-dell. It will be ready in a few minutes.', 10);

  let data;
  try {
    const res = await fetchWithTimeout(LIVE_DATA_URL + '?t=' + Date.now() + (forceRefresh ? '&refresh=1' : ''), { mode: 'cors' }, poll ? 25000 : FETCH_TIMEOUT);
    if (res.ok) data = await res.json();
  } catch (e) {
    console.warn('Live data failed:', e);
  }

  const isRefreshing = data?.refreshing === true;

  if (data && data.ok && !isRefreshing) {
    if (live) live.textContent = 'Live data from tony-dell';
    currentReportData = data;
    stopRefreshPoll();
    try {
      const prevRes = await fetchWithTimeout(PREVIOUS_DATA_URL + '?t=' + Date.now());
      if (prevRes.ok) previousReportData = await prevRes.json();
    } catch (e) {
      previousReportData = null;
    }
  } else {
    if (live) live.textContent = isRefreshing ? 'Live refresh in progress on tony-dell...' : 'Live data unavailable; showing cached snapshot.';
    if (data) {
      data.ok = data.ok && !isRefreshing;
      currentReportData = data;
    } else {
      try {
        const res = await fetchWithTimeout('data/mcp-savings.json?t=' + Date.now());
        if (res.ok) data = await res.json();
        currentReportData = data;
      } catch (e) {
        console.warn('Cached fallback failed:', e);
      }
    }
    // If the server is still refreshing, start polling for the new report.
    if (isRefreshing && !refreshPollId) startRefreshPoll();
  }

  try {
    if (!data || (!data.ok && !data.total_raw_chars)) throw new Error(data?.error || 'report not ok');
    renderReport(data);
    const generated = data.generated ? new Date(data.generated).toLocaleString() : 'unknown';
    const source = data.freshness && data.ok ? 'Live' : 'Snapshot';
    status.innerHTML = `${source}: <span class="font-mono">${generated}</span>`;
    if (meta && data.freshness) {
      const age = formatAge(data.freshness.cache_age_ms);
      const duration = data.freshness.duration_ms != null ? `, took ${data.freshness.duration_ms.toFixed(0)}ms` : '';
      meta.textContent = `collected ${new Date(data.freshness.collected_at).toLocaleTimeString()}, cached ${age} ago${duration}`;
    }
  } catch (e) {
    status.textContent = 'Error';
    document.getElementById('report').innerHTML = `<p style="color:#dc2626">Failed to load report: ${escapeHtml(e.message)}</p>`;
  } finally {
    if (!refreshPollId) {
      hideProgress();
      setLoading(false);
    }
  }
}

function renderSummary(data) {
  const el = document.getElementById('summary');
  const hosts = data.hosts ? Object.keys(data.hosts).length : 0;
  const raw = data.total_raw_chars || 0;
  const compact = data.total_compact_chars || 0;
  const saved = data.total_saved_chars || 0;
  const pct = data.total_savings_pct != null ? data.total_savings_pct.toFixed(1) : '0.0';
  const prefixes = data.raw_allowed ? data.raw_allowed.length : 0;
  const presets = data.presets ? data.presets.length : 0;
  const cards = [
    { label: 'Total raw', value: formatNumber(raw) },
    { label: 'Total compact', value: formatNumber(compact) },
    { label: 'Saved chars', value: formatNumber(saved) },
    { label: 'Savings %', value: pct + '%' },
    { label: 'Hosts', value: hosts },
    { label: 'Raw prefixes', value: prefixes },
  ];
  el.innerHTML = cards.map(c => `
    <div class="summary-card">
      <div class="summary-value">${c.value}</div>
      <div class="summary-label">${c.label}</div>
    </div>
  `).join('');
}

function commandStatus(c) {
  if (!c.ok) return { text: 'failed', cls: 'badge-failed' };
  if ((c.savings_pct_chars || 0) < 0) return { text: 'negative', cls: 'badge-warning' };
  return { text: 'recommended', cls: 'badge-recommended' };
}

function collectAudit(hosts) {
  const failed = [];
  const negative = [];
  if (!hosts) return { failed, negative };
  for (const [host, hdata] of Object.entries(hosts)) {
    for (const [cmd, c] of Object.entries(hdata.commands || {})) {
      const row = { ...c, host, command: c.command || cmd };
      if (!c.ok) failed.push(row);
      else if ((c.savings_pct_chars || 0) < 0) negative.push(row);
    }
  }
  failed.sort((a, b) => (a.savings_pct_chars || 0) - (b.savings_pct_chars || 0));
  negative.sort((a, b) => (a.savings_pct_chars || 0) - (b.savings_pct_chars || 0));
  return { failed, negative };
}

function renderAudit(data) {
  const el = document.getElementById('audit');
  const { failed, negative } = collectAudit(data.hosts);
  if (!failed.length && !negative.length) {
    el.classList.add('hidden');
    return;
  }
  el.classList.remove('hidden');
  let html = '<h2 class="text-lg font-semibold mb-2">Needs attention</h2>';
  if (failed.length) {
    html += `<p class="text-sm text-gray-700 mb-2">${failed.length} command(s) failed on at least one host.</p>`;
    html += '<table><thead><tr><th>Host</th><th>Command</th><th>Status</th><th>Raw</th><th>Compact</th></tr></thead><tbody>';
    for (const c of failed.slice(0, 20)) {
      html += `<tr>
        <td>${c.host}</td>
        <td>${escapeHtml(c.command)}</td>
        <td><span class="badge badge-failed">failed</span></td>
        <td>${c.raw_chars}</td>
        <td>${c.compact_chars}</td>
      </tr>`;
    }
    html += '</tbody></table>';
  }
  if (negative.length) {
    html += `<p class="text-sm text-gray-700 mb-2">${negative.length} command(s) have negative savings.</p>`;
    html += '<table><thead><tr><th>Host</th><th>Command</th><th>Saved chars</th><th>Savings %</th></tr></thead><tbody>';
    for (const c of negative.slice(0, 20)) {
      const cls = c.saved_chars < 0 ? 'negative' : '';
      html += `<tr>
        <td>${c.host}</td>
        <td>${escapeHtml(c.command)}</td>
        <td class="${cls}">${c.saved_chars}</td>
        <td class="${cls}">${(c.savings_pct_chars || 0).toFixed(1)}%</td>
      </tr>`;
    }
    html += '</tbody></table>';
  }
  el.innerHTML = html;
}

function renderRawAllowed(rawAllowed) {
  if (!rawAllowed || !rawAllowed.length) return '';
  const byCat = {};
  for (const r of rawAllowed) {
    const cat = r.category || 'other';
    if (!byCat[cat]) byCat[cat] = [];
    byCat[cat].push(r);
  }
  let html = '<h2 class="text-xl font-semibold mt-8 mb-2">Raw-allowed command prefixes</h2>';
  for (const cat of Object.keys(byCat).sort()) {
    html += `<div class="mb-4">
      <h3 class="text-sm font-semibold text-gray-600 mb-1 uppercase">${escapeHtml(cat)}</h3>
      <div>`;
    for (const r of byCat[cat]) {
      html += `<span class="category-pill" title="${escapeHtml(r.example || '')}">${escapeHtml(r.prefix)}</span>`;
    }
    html += '</div></div>';
  }
  return html;
}

function renderPresets(presets) {
  if (!presets || !presets.length) return '';
  const sorted = [...presets].sort((a, b) => (b.preset_score || 0) - (a.preset_score || 0));
  let html = '<h2 class="text-xl font-semibold mt-8 mb-2">Registered presets</h2>';
  for (const p of sorted) {
    const score = p.preset_score != null ? p.preset_score.toFixed(1) : '0.0';
    const color = p.ok ? (score >= 30 ? '#16a34a' : (score >= 0 ? '#f59e0b' : '#dc2626')) : '#9ca3af';
    const width = Math.min(100, Math.max(0, (p.preset_score || 0) + 20)) + '%';
    html += `<div class="preset-row">
      <div class="w-48 text-sm truncate" title="${escapeHtml(p.description || '')}">${escapeHtml(p.name)}</div>
      <div class="preset-bar"><div class="preset-fill" style="width:${width}; background:${color};"></div></div>
      <div class="w-12 text-right text-sm font-mono">${score}</div>
      <div class="w-16 text-xs text-gray-500">${p.ok ? 'ok' : 'failed'}</div>
    </div>`;
  }
  return html;
}

function renderWhatsNew(current, previous) {
  const el = document.getElementById('whats-new');
  if (!previous || !current) {
    el.classList.add('hidden');
    return;
  }
  const curPrefixes = new Set((current.raw_allowed || []).map(r => r.prefix));
  const prevPrefixes = new Set((previous.raw_allowed || []).map(r => r.prefix));
  const added = [...curPrefixes].filter(x => !prevPrefixes.has(x));
  const removed = [...prevPrefixes].filter(x => !curPrefixes.has(x));
  const curPresets = new Set((current.presets || []).map(p => p.name));
  const prevPresets = new Set((previous.presets || []).map(p => p.name));
  const addedPresets = [...curPresets].filter(x => !prevPresets.has(x));
  if (!added.length && !removed.length && !addedPresets.length) {
    el.classList.add('hidden');
    return;
  }
  el.classList.remove('hidden');
  let html = '<h2 class="text-lg font-semibold mb-2">What changed since last snapshot</h2><div class="flex flex-wrap gap-2 text-sm">';
  for (const p of added) html += `<span class="diff-added">+ ${escapeHtml(p)}</span>`;
  for (const p of removed) html += `<span class="diff-removed">- ${escapeHtml(p)}</span>`;
  for (const p of addedPresets) html += `<span class="diff-added">+ preset ${escapeHtml(p)}</span>`;
  html += '</div>';
  el.innerHTML = html;
}

function renderCommandTables(data, filter = '') {
  const report = document.getElementById('report');
  if (!data || !data.hosts) return;
  const lower = filter.toLowerCase();
  const hosts = Object.entries(data.hosts).sort(([a], [b]) => a.localeCompare(b));
  let html = '';
  for (const [host, hdata] of hosts) {
    const commands = Object.values(hdata.commands || {})
      .filter(c => !lower || (c.command || '').toLowerCase().includes(lower))
      .sort((a, b) => (b.savings_pct_chars || 0) - (a.savings_pct_chars || 0));
    if (filter && !commands.length) continue;
    html += `<h2 class="text-xl font-semibold mt-8 mb-2 flex items-center gap-2">
      <span class="w-3 h-3 rounded-full" style="background:#22c55e"></span>${host}
    </h2>`;
    html += '<table><thead><tr>';
    html += '<th>Command</th><th>Status</th><th>Raw chars</th><th>Compact chars</th><th>Saved chars</th><th>Tokens saved</th><th>Char %</th><th>Word %</th><th>Action</th>';
    html += '</tr></thead><tbody>';
    for (const c of commands) {
      const st = commandStatus(c);
      const savedNegative = (c.saved_chars || 0) < 0 ? 'negative' : '';
      const tokens = Math.round((c.saved_chars || 0) / 4);
      html += `<tr data-host="${host}" data-command="${escapeHtml(c.command)}">
        <td>${escapeHtml(c.command)}</td>
        <td><span class="badge ${st.cls}">${st.text}</span></td>
        <td>${formatNumber(c.raw_chars)}</td>
        <td>${formatNumber(c.compact_chars)}</td>
        <td class="${savedNegative}">${formatNumber(c.saved_chars)}</td>
        <td class="${savedNegative}">${formatNumber(tokens)}</td>
        <td class="${(c.savings_pct_chars || 0) < 0 ? 'negative' : ''}">${(c.savings_pct_chars || 0).toFixed(1)}%</td>
        <td>${(c.savings_pct || 0).toFixed(1)}%</td>
        <td><button class="text-sm text-blue-600 hover:underline detail-btn" data-host="${host}" data-command="${escapeHtml(c.command)}">Detail</button></td>
      </tr>`;
    }
    html += '</tbody></table>';
    html += `<p class="totals text-sm"><strong>${host} totals</strong>: `;
    html += `raw=${formatNumber(hdata.raw_chars)}, compact=${formatNumber(hdata.compact_chars)}, saved=${formatNumber(hdata.saved_chars)}, tokens=${formatNumber(Math.round(hdata.saved_chars / 4))} `;
    html += `(${(hdata.saved_chars ? ((hdata.saved_chars / hdata.raw_chars) * 100).toFixed(1) : '0.0')}%)</p>`;
  }
  html += renderRawAllowed(data.raw_allowed);
  html += renderPresets(data.presets);
  report.innerHTML = html;
  report.querySelectorAll('.detail-btn').forEach(b => b.addEventListener('click', (e) => {
    const host = e.target.dataset.host;
    const command = e.target.dataset.command;
    loadTable(host, command);
  }));
}

function renderReport(data) {
  renderSummary(data);
  renderWhatsNew(data, previousReportData);
  renderAudit(data);
  renderCommandTables(data, document.getElementById('command-search').value);
}

async function loadTable(host, command) {
  const title = document.getElementById('modal-title');
  const body = document.getElementById('modal-body');
  const modal = document.getElementById('modal');
  title.textContent = `${host} — ${command}`;
  body.innerHTML = '<p class="text-gray-500">Loading...</p>';
  modal.style.display = 'flex';
  modal.classList.remove('hidden');
  try {
    const res = await fetchWithTimeout(`${TABLE_DATA_URL}?host=${encodeURIComponent(host)}&command=${encodeURIComponent(command)}&t=${Date.now()}`);
    const data = await res.json();
    if (!data.ok) throw new Error(data.error || 'detail unavailable');
    let html = '';
    if (data.headers && data.headers.length) {
      html += '<div><h3 class="font-semibold mb-2">Compact table</h3><table><thead><tr>';
      for (const h of data.headers) html += `<th>${escapeHtml(h)}</th>`;
      html += '</tr></thead><tbody>';
      for (const row of data.rows) {
        html += '<tr>';
        for (const cell of row) html += `<td>${escapeHtml(cell)}</td>`;
        html += '</tr>';
      }
      html += '</tbody></table></div>';
    } else {
      html += '<div><h3 class="font-semibold mb-2">Compact output</h3><pre class="modal-pre">' + escapeHtml(JSON.stringify(data.compact_out, null, 2)) + '</pre></div>';
    }
    html += '<div><h3 class="font-semibold mb-2">Raw output</h3><pre class="modal-pre">' + escapeHtml(data.raw_out || '(none)') + '</pre></div>';
    body.innerHTML = html;
  } catch (e) {
    body.innerHTML = `<p style="color:#dc2626">Failed to load detail: ${escapeHtml(e.message)}</p>`;
  }
}

function closeModal() {
  const modal = document.getElementById('modal');
  modal.style.display = 'none';
  modal.classList.add('hidden');
}

function downloadJson() {
  if (!currentReportData) return;
  const blob = new Blob([JSON.stringify(currentReportData, null, 2)], { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'mcp-savings.json';
  a.click();
  URL.revokeObjectURL(a.href);
}

function startAutoRefresh() {
  stopAutoRefresh();
  autoRefreshId = setInterval(() => loadReport(false), 60000);
}

function stopAutoRefresh() {
  if (autoRefreshId) { clearInterval(autoRefreshId); autoRefreshId = null; }
}

document.getElementById('refresh').addEventListener('click', () => loadReport(true));
document.getElementById('download').addEventListener('click', downloadJson);
document.getElementById('modal-close').addEventListener('click', closeModal);
document.getElementById('modal').addEventListener('click', (e) => { if (e.target.id === 'modal') closeModal(); });
document.getElementById('command-search').addEventListener('input', (e) => {
  if (currentReportData) renderCommandTables(currentReportData, e.target.value);
});
document.getElementById('auto-refresh').addEventListener('change', (e) => {
  e.target.checked ? startAutoRefresh() : stopAutoRefresh();
});

loadReport();
