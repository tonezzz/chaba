const LIVE_DATA_URL = "https://tony-omen.taila0626a.ts.net/mcp-savings.json";
const PREVIOUS_DATA_URL = "/apps/docs/mcp_debug/data/mcp-savings-previous.json";
const TABLE_DATA_URL = "/api/mcp-table.php";
const TABLE_LIVE_URL = "https://tony-omen.taila0626a.ts.net/mcp-table.json";
const FETCH_TIMEOUT = 130000;

let currentReportData = null;
let previousReportData = null;
let autoRefreshId = null;
let refreshPollId = null;
let currentCommandHost = 'all';

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
      showTab(currentTab);
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

function renderStatusBreakdown(data) {
  const el = document.getElementById('status-breakdown');
  if (!data || !data.hosts) { el.innerHTML = ''; return; }
  const counts = { recommended: 0, negative: 0, failed: 0 };
  for (const [host, hdata] of Object.entries(data.hosts)) {
    for (const c of Object.values(hdata.commands || {})) {
      const st = commandStatus(c);
      if (st.text === 'failed') counts.failed++;
      else if (st.text === 'negative') counts.negative++;
      else counts.recommended++;
    }
  }
  const total = counts.recommended + counts.negative + counts.failed;
  const chips = [
    { label: 'Recommended', value: counts.recommended, color: '#dcfce7', text: '#166534' },
    { label: 'Negative savings', value: counts.negative, color: '#fef3c7', text: '#92400e' },
    { label: 'Failed', value: counts.failed, color: '#fee2e2', text: '#991b1b' },
    { label: 'Total commands', value: total, color: '#e0f2fe', text: '#0c4a6e' }
  ];
  el.innerHTML = chips.map(c => `
    <div class="status-chip">
      <div class="summary-value" style="background:${c.color}; color:${c.text}; border-radius:9999px; padding:0.25rem 0.75rem; display:inline-block;">${c.value}</div>
      <div class="summary-label mt-1">${c.label}</div>
    </div>
  `).join('');
}

function renderTopCommands(data) {
  const el = document.getElementById('top-commands');
  if (!data || !data.hosts) { el.innerHTML = ''; return; }
  const topN = 10;
  let html = '<h2 class="text-xl font-semibold mt-6 mb-2">Top commands by character savings</h2>';
  html += '<p class="text-sm text-gray-500 mb-3">The 10 commands with the largest positive character savings on each host.</p>';
  const hosts = Object.entries(data.hosts).sort(([a], [b]) => a.localeCompare(b));
  for (const [host, hdata] of hosts) {
    const commands = Object.values(hdata.commands || {})
      .filter(c => (c.savings_pct_chars || 0) > 0)
      .sort((a, b) => (b.savings_pct_chars || 0) - (a.savings_pct_chars || 0))
      .slice(0, topN);
    if (!commands.length) continue;
    html += `<h3 class="text-lg font-semibold mt-4 mb-2">${host}</h3>`;
    for (const c of commands) {
      const width = Math.min(100, Math.max(0, c.savings_pct_chars || 0));
      const color = width > 70 ? '#16a34a' : '#0a84ff';
      html += `<div class="preset-row">
        <div class="w-64 text-sm truncate" title="${escapeHtml(c.command)}">${escapeHtml(c.command)}</div>
        <div class="preset-bar"><div class="preset-fill" style="width:${width}%; background:${color};"></div></div>
        <div class="w-16 text-right text-sm font-mono">${width.toFixed(1)}%</div>
      </div>`;
    }
  }
  el.innerHTML = html || '<p class="text-sm text-gray-500">No positive savings to show.</p>';
}

function renderRawAllowed(rawAllowed) {
  const el = document.getElementById('raw-allowed');
  if (!el) return;
  if (!rawAllowed || !rawAllowed.length) { el.innerHTML = '<p class="text-sm text-gray-500">No raw-allowed prefixes configured.</p>'; return; }
  const byCat = {};
  for (const r of rawAllowed) {
    const cat = r.category || 'other';
    if (!byCat[cat]) byCat[cat] = [];
    byCat[cat].push(r);
  }
  let html = '<h2 class="text-xl font-semibold mt-4 mb-2">Raw-allowed command prefixes</h2>';
  for (const cat of Object.keys(byCat).sort()) {
    html += `<div class="mb-4">
      <h3 class="text-sm font-semibold text-gray-600 mb-1 uppercase">${escapeHtml(cat)}</h3>
      <div>`;
    for (const r of byCat[cat]) {
      html += `<span class="category-pill" title="${escapeHtml(r.example || '')}">${escapeHtml(r.prefix)}</span>`;
    }
    html += '</div></div>';
  }
  el.innerHTML = html;
}

function renderPresets(presets) {
  const el = document.getElementById('presets');
  if (!el) return;
  if (!presets || !presets.length) { el.innerHTML = '<p class="text-sm text-gray-500">No presets registered.</p>'; return; }
  const sorted = [...presets].sort((a, b) => (b.preset_score || 0) - (a.preset_score || 0));
  let html = '<h2 class="text-xl font-semibold mt-4 mb-2">Registered presets</h2>';
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
  el.innerHTML = html;
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

function renderHostTabs(hosts) {
  const el = document.getElementById('host-tabs');
  if (!el) return;
  let html = `<button class="host-tab px-3 py-1.5 text-sm font-medium ${currentCommandHost === 'all' ? 'active' : ''}" data-host="all" role="tab" aria-selected="${currentCommandHost === 'all'}">All hosts</button>`;
  for (const [host] of hosts) {
    html += `<button class="host-tab px-3 py-1.5 text-sm font-medium ${currentCommandHost === host ? 'active' : ''}" data-host="${escapeHtml(host)}" role="tab" aria-selected="${currentCommandHost === host}">${escapeHtml(host)}</button>`;
  }
  el.innerHTML = html;
}

function renderCommandTables(data, { filter = '', sortKey = 'savings_pct_chars' } = {}) {
  const report = document.getElementById('report');
  const searchMeta = document.getElementById('search-meta');
  if (!data || !data.hosts) { report.innerHTML = ''; return; }
  const lower = filter.toLowerCase();
  const hosts = Object.entries(data.hosts).sort(([a], [b]) => a.localeCompare(b));
  renderHostTabs(hosts);
  const sortDirections = {
    savings_pct_chars: -1,
    saved_chars: -1,
    raw_chars: -1,
    command: 1,
  };
  const dir = sortDirections[sortKey] || -1;
  const sortFn = (a, b) => {
    if (sortKey === 'command') return a.command.localeCompare(b.command) * dir;
    const av = a[sortKey] != null ? a[sortKey] : -Infinity;
    const bv = b[sortKey] != null ? b[sortKey] : -Infinity;
    return (av - bv) * dir;
  };
  let html = '';
  let total = 0, shown = 0;
  for (const [host, hdata] of hosts) {
    if (currentCommandHost !== 'all' && currentCommandHost !== host) continue;
    const allCommands = Object.values(hdata.commands || {});
    const commands = allCommands
      .filter(c => !lower || (c.command || '').toLowerCase().includes(lower))
      .sort(sortFn);
    total += allCommands.length;
    shown += commands.length;
    if (filter && !commands.length) continue;
    if (currentCommandHost === 'all') {
      html += `<h2 class="text-xl font-semibold mt-8 mb-2 flex items-center gap-2">
        <span class="w-3 h-3 rounded-full" style="background:#22c55e"></span>${host}
      </h2>`;
    }
    html += '<table><thead><tr>';
    html += '<th>#</th><th>Command</th><th>Status</th><th>Raw chars</th><th>Compact chars</th><th>Saved chars</th><th>Tokens saved</th><th style="min-width:160px">Savings</th><th>Word %</th><th>Action</th>';
    html += '</tr></thead><tbody>';
    for (const [idx, c] of commands.entries()) {
      const st = commandStatus(c);
      const savedNegative = (c.saved_chars || 0) < 0 ? 'negative' : '';
      const tokens = Math.round((c.saved_chars || 0) / 4);
      const savingsWidth = Math.min(100, Math.max(0, c.savings_pct_chars || 0));
      const savingsColor = c.savings_pct_chars < 0 ? '#dc2626' : savingsWidth > 70 ? '#16a34a' : '#0a84ff';
      html += `<tr data-host="${host}" data-command="${escapeHtml(c.command)}">
        <td class="text-right text-xs text-gray-500 font-mono">${idx + 1}</td>
        <td>${escapeHtml(c.command)}</td>
        <td><span class="badge ${st.cls}">${st.text}</span></td>
        <td>${formatNumber(c.raw_chars)}</td>
        <td>${formatNumber(c.compact_chars)}</td>
        <td class="${savedNegative}">${formatNumber(c.saved_chars)}</td>
        <td class="${savedNegative}">${formatNumber(tokens)}</td>
        <td><div class="flex items-center gap-2"><div class="savings-bar"><div class="savings-fill" style="width:${savingsWidth}%; background:${savingsColor};"></div></div><span class="${(c.savings_pct_chars || 0) < 0 ? 'negative' : ''}">${(c.savings_pct_chars || 0).toFixed(1)}%</span></div></td>
        <td>${(c.savings_pct || 0).toFixed(1)}%</td>
        <td><button class="text-sm text-blue-600 hover:underline detail-btn" data-host="${host}" data-command="${escapeHtml(c.command)}">Detail</button></td>
      </tr>`;
    }
    html += '</tbody></table>';
    html += `<p class="totals text-sm"><strong>${host} totals</strong>: `;
    html += `raw=${formatNumber(hdata.raw_chars)}, compact=${formatNumber(hdata.compact_chars)}, saved=${formatNumber(hdata.saved_chars)}, tokens=${formatNumber(Math.round(hdata.saved_chars / 4))} `;
    html += `(${(hdata.saved_chars ? ((hdata.saved_chars / hdata.raw_chars) * 100).toFixed(1) : '0.0')}%)</p>`;
  }
  report.innerHTML = html;
  report.querySelectorAll('.detail-btn').forEach(b => b.addEventListener('click', (e) => {
    const host = e.target.dataset.host;
    const command = e.target.dataset.command;
    loadTable(host, command);
  }));
  searchMeta.classList.remove('hidden');
  searchMeta.textContent = filter
    ? `Showing ${shown} of ${total} commands matching "${escapeHtml(filter)}"`
    : `Showing ${shown} commands`;
}

let currentTab = 'overview';

function renderRawJson(data) {
  const el = document.getElementById('raw-json');
  if (el) el.textContent = JSON.stringify(data, null, 2);
}

function showTab(tab) {
  currentTab = tab;
  document.querySelectorAll('.tab').forEach(b => {
    const isActive = b.dataset.tab === tab;
    b.classList.toggle('active', isActive);
    b.setAttribute('aria-selected', isActive ? 'true' : 'false');
  });
  document.querySelectorAll('.tab-panel').forEach(p => {
    p.classList.toggle('hidden', p.id !== `tab-${tab}`);
  });
}

function renderReport(data) {
  renderSummary(data);
  renderStatusBreakdown(data);
  renderWhatsNew(data, previousReportData);
  renderAudit(data);
  renderTopCommands(data);
  renderCommandTables(data, { filter: document.getElementById('command-search').value, sortKey: document.getElementById('command-sort').value });
  renderRawAllowed(data.raw_allowed);
  renderPresets(data.presets);
  renderRawJson(data);
}

async function loadTable(host, command) {
  const title = document.getElementById('modal-title');
  const body = document.getElementById('modal-body');
  const modal = document.getElementById('modal');
  title.textContent = `${host} — ${command}`;
  body.innerHTML = '<p class="text-gray-500">Loading...</p>';
  modal.style.display = 'flex';
  modal.classList.remove('hidden');
  let data;
  try {
    const liveRes = await fetchWithTimeout(`${TABLE_LIVE_URL}?host=${encodeURIComponent(host)}&command=${encodeURIComponent(command)}&t=${Date.now()}`, { mode: 'cors' }, 15000);
    if (liveRes.ok) data = await liveRes.json();
  } catch (e) { console.warn('Live table failed:', e); }
  if (!data) {
    try {
      const res = await fetchWithTimeout(`${TABLE_DATA_URL}?host=${encodeURIComponent(host)}&command=${encodeURIComponent(command)}&t=${Date.now()}`);
      if (res.ok) data = await res.json();
    } catch (e) { console.warn('Proxy table failed:', e); }
  }
  try {
    if (!data || !data.ok) throw new Error(data?.error || 'detail unavailable');
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

function toggleHelp(show) {
  const el = document.getElementById('how-to');
  const btn = document.getElementById('help-toggle');
  el.classList.toggle('hidden', !show);
  if (btn) btn.textContent = show ? 'Hide help' : 'Show help';
}

function setupEventListeners() {
  document.getElementById('refresh').addEventListener('click', () => loadReport(true));
  document.getElementById('download').addEventListener('click', downloadJson);
  document.getElementById('modal-close').addEventListener('click', closeModal);
  document.getElementById('modal').addEventListener('click', (e) => { if (e.target.id === 'modal') closeModal(); });
  document.getElementById('command-search').addEventListener('input', (e) => {
    if (currentReportData) renderCommandTables(currentReportData, { filter: e.target.value, sortKey: document.getElementById('command-sort').value });
  });
  document.getElementById('command-sort').addEventListener('change', (e) => {
    if (currentReportData) renderCommandTables(currentReportData, { filter: document.getElementById('command-search').value, sortKey: e.target.value });
  });
  document.getElementById('auto-refresh').addEventListener('change', (e) => {
    e.target.checked ? startAutoRefresh() : stopAutoRefresh();
  });
  document.getElementById('tabs').addEventListener('click', (e) => {
    const tab = e.target.closest('.tab')?.dataset.tab;
    if (tab) showTab(tab);
  });
  document.getElementById('host-tabs').addEventListener('click', (e) => {
    const host = e.target.closest('.host-tab')?.dataset.host;
    if (host && currentReportData) {
      currentCommandHost = host;
      renderCommandTables(currentReportData, { filter: document.getElementById('command-search').value, sortKey: document.getElementById('command-sort').value });
    }
  });
  const helpToggle = document.getElementById('help-toggle');
  const helpClose = document.getElementById('help-close');
  if (helpToggle) helpToggle.addEventListener('click', () => {
    const el = document.getElementById('how-to');
    toggleHelp(el.classList.contains('hidden'));
  });
  if (helpClose) helpClose.addEventListener('click', () => toggleHelp(false));
}

setupEventListeners();
loadReport();
