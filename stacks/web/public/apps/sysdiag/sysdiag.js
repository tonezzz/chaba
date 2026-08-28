(function () {
  'use strict';

  const DEFAULT_URL = '/apps/sysdiag/sysdiag.yml';

  const STATUS_COLORS = {
    healthy: '#4ade80',
    degraded: '#fbbf24',
    error: '#ef4444',
    offline: '#64748b',
    unknown: '#94a3b8'
  };

  const NODE_WIDTH = 120;
  const NODE_HEIGHT = 48;

  const state = {
    data: null,
    byId: new Map(),
    health: new Map(),
    selected: null,
    auto: true,
    timer: null
  };

  function $(id) {
    return document.getElementById(id);
  }

  async function loadYaml(url) {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return jsyaml.load(await res.text());
  }

  function buildIndex(data) {
    const byId = new Map();
    for (const c of (data.components || [])) {
      byId.set(c.id, Object.assign({}, c, { kind: 'component' }));
    }
    for (const e of (data.connections || [])) {
      const key = e.id || `${e.from}-${e.to}`;
      byId.set(key, Object.assign({}, e, { kind: 'connection', key }));
    }
    return byId;
  }

  function layout(data) {
    const components = data.components || [];
    const layoutCfg = data.layout || {};
    const width = layoutCfg.width || 900;
    const height = layoutCfg.height || 500;
    const cx = width / 2;
    const cy = height / 2;
    const radius = Math.min(width, height) * 0.35;

    if (layoutCfg.auto !== false && components.some(c => typeof c.x !== 'number' || typeof c.y !== 'number')) {
      components.forEach((c, i) => {
        if (typeof c.x !== 'number' || typeof c.y !== 'number') {
          const n = components.length;
          const angle = (i / n) * Math.PI * 2 - Math.PI / 2;
          c.x = Math.round(cx + radius * Math.cos(angle));
          c.y = Math.round(cy + radius * Math.sin(angle));
        }
      });
    }

    data.width = width;
    data.height = height;
  }

  function escapeHtml(s) {
    if (s == null) return '';
    return String(s).replace(/[&<>"']/g, m => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[m]));
  }

  function statusColor(id, item) {
    const h = state.health.get(id);
    if (h && STATUS_COLORS[h.status]) return STATUS_COLORS[h.status];
    if (item && item.status && STATUS_COLORS[item.status]) return STATUS_COLORS[item.status];
    return STATUS_COLORS.unknown;
  }

  function render() {
    const data = state.data;
    if (!data) return;

    layout(data);
    const svg = $('diagram');
    svg.setAttribute('viewBox', `0 0 ${data.width} ${data.height}`);
    svg.setAttribute('width', String(data.width));
    svg.setAttribute('height', String(data.height));

    // Rebuild SVG; keep defs first
    svg.innerHTML = `
      <defs>
        <marker id="sys-arrow" viewBox="0 0 10 10" refX="8" refY="5"
                markerWidth="6" markerHeight="6" orient="auto-start-reverse">
          <path d="M 0 0 L 10 5 L 0 10 z" fill="#475569" />
        </marker>
      </defs>
    `;

    for (const c of (data.connections || [])) renderEdge(svg, c);
    for (const c of (data.components || [])) renderNode(svg, c);
  }

  function nodePort(c, side) {
    const halfW = NODE_WIDTH / 2;
    return side === 'out'
      ? { x: c.x + halfW, y: c.y }
      : { x: c.x - halfW, y: c.y };
  }

  function renderNode(svg, c) {
    const x = c.x - NODE_WIDTH / 2;
    const y = c.y - NODE_HEIGHT / 2;
    const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    g.classList.add('sys-node');
    if (state.selected === c.id) g.classList.add('selected');
    g.setAttribute('data-id', c.id);
    g.setAttribute('transform', `translate(${x}, ${y})`);
    g.innerHTML = `
      <rect class="sys-node-rect" x="0" y="0" width="${NODE_WIDTH}" height="${NODE_HEIGHT}" rx="6" />
      <circle class="sys-node-status" cx="${NODE_WIDTH - 12}" cy="12" r="5" fill="${statusColor(c.id, c)}" />
      <text class="sys-node-label" x="${NODE_WIDTH / 2}" y="${NODE_HEIGHT / 2}">${escapeHtml(c.label || c.id)}</text>
    `;
    g.addEventListener('click', () => select(c.id));
    svg.appendChild(g);
  }

  function renderEdge(svg, c) {
    const from = state.byId.get(c.from);
    const to = state.byId.get(c.to);
    if (!from || !to) return;

    const p1 = nodePort(from, 'out');
    const p2 = nodePort(to, 'in');
    const cx1 = p1.x;
    const cy1 = p1.y + 40;
    const cx2 = p2.x;
    const cy2 = p2.y - 40;
    const d = `M ${p1.x} ${p1.y} C ${cx1} ${cy1}, ${cx2} ${cy2}, ${p2.x} ${p2.y}`;
    const key = c.id || `${c.from}-${c.to}`;
    const hasEvents = Array.isArray(c.events) && c.events.length > 0;

    const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    g.classList.add('sys-edge-group');
    if (state.selected === key) g.classList.add('selected');
    g.setAttribute('data-id', key);
    g.innerHTML = `
      <path class="sys-edge${hasEvents ? ' active' : ''}" d="${d}" marker-end="url(#sys-arrow)" />
      <text class="sys-edge-label" x="${(p1.x + p2.x) / 2}" y="${(p1.y + p2.y) / 2 - 6}">${escapeHtml(c.label || '')}</text>
    `;
    g.addEventListener('click', () => select(key));
    svg.appendChild(g);
  }

  function select(id) {
    state.selected = id;
    render(); // update selected stroke
    const item = state.byId.get(id);
    const panel = $('sidebar');
    if (!item) {
      panel.innerHTML = '<div class="sys-empty">Item not found.</div>';
      return;
    }

    const kind = item.kind === 'connection' ? 'Connection' : 'Component';
    const health = state.health.get(id);
    const statusName = health ? health.status : (item.status || 'unknown');

    let html = `<h2 class="sys-title">${escapeHtml(item.label || item.id || 'Item')}</h2>`;
    html += `<div class="sys-kv"><span>ID</span><span>${escapeHtml(item.id || '')}</span></div>`;
    html += `<div class="sys-kv"><span>Kind</span><span>${kind}</span></div>`;
    if (item.type) html += `<div class="sys-kv"><span>Type</span><span>${escapeHtml(item.type)}</span></div>`;
    html += `<div class="sys-kv"><span>Status</span><span>${escapeHtml(statusName)}</span></div>`;
    if (health && health.code) html += `<div class="sys-kv"><span>HTTP</span><span>${health.code}</span></div>`;
    if (health && health.error) html += `<div class="sys-kv"><span>Error</span><span>${escapeHtml(health.error)}</span></div>`;
    if (item.detail) {
      html += `<div class="sys-section-title">Detail</div>`;
      html += `<p class="sys-detail">${escapeHtml(item.detail)}</p>`;
    }

    html += `<div class="sys-section-title">Recent events</div>`;
    const events = [];
    for (const ev of (state.data.events || [])) {
      if (ev.component === id || ev.connection === id) events.push(ev);
    }
    if (item.kind === 'connection' && Array.isArray(item.events)) {
      for (const ev of item.events) events.push(Object.assign({}, ev, { connection: id }));
    }

    if (!events.length) {
      html += '<div class="sys-empty">No events for this item.</div>';
    } else {
      events.sort((a, b) => String(b.time || '').localeCompare(String(a.time || '')));
      for (const ev of events.slice(0, 20)) {
        html += `
          <div class="sys-event">
            <time>${escapeHtml(ev.time || '')}</time>
            <div class="msg">${escapeHtml(ev.message || '')}</div>
          </div>
        `;
      }
    }

    panel.innerHTML = html;
  }

  async function refreshHealth() {
    if (!state.data) return;
    for (const c of (state.data.components || [])) {
      if (!c.url) continue;
      try {
        const ctrl = new AbortController();
        const t = setTimeout(() => ctrl.abort(), 5000);
        const res = await fetch(c.url, { signal: ctrl.signal, mode: 'cors', cache: 'no-store' });
        clearTimeout(t);
        let status = 'unknown';
        if (res.ok) status = 'healthy';
        else if (res.status >= 500) status = 'error';
        else status = 'degraded';
        state.health.set(c.id, { status, code: res.status, at: new Date().toISOString() });
      } catch (err) {
        state.health.set(c.id, { status: 'unknown', error: err.message, at: new Date().toISOString() });
      }
    }
    render();
    if (state.selected) select(state.selected);
  }

  function startAuto() {
    if (state.timer) clearInterval(state.timer);
    if (!state.auto || !state.data) return;
    const seconds = state.data.refresh ? Number(state.data.refresh) : 30;
    const ms = Math.max(5000, seconds * 1000);
    state.timer = setInterval(refreshHealth, ms);
  }

  async function load(url) {
    try {
      const data = await loadYaml(url);
      state.data = data;
      state.byId = buildIndex(data);
      $('page-title').textContent = data.title || 'Sysdiag';
      $('page-desc').textContent = data.description || '';
      layout(data);
      render();
      startAuto();
      await refreshHealth();
    } catch (err) {
      $('page-desc').textContent = `Error loading YAML: ${err.message}`;
      console.error(err);
    }
  }

  function init() {
    $('btn-load').addEventListener('click', () => {
      const url = $('yaml-url').value.trim() || DEFAULT_URL;
      load(url);
    });
    $('btn-reload').addEventListener('click', () => {
      const url = $('yaml-url').value.trim() || DEFAULT_URL;
      load(url);
    });
    $('auto-refresh').addEventListener('change', (e) => {
      state.auto = e.target.checked;
      startAuto();
    });

    load(DEFAULT_URL);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
}());
