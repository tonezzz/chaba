// Pigeon race dashboard — loads pegion.yml and renders sections.
// Data captured from pattayaoneloftrace.com/en (July 2026 snapshot).

const KIND_LABELS = {
  hotspot: 'Hotspot',
  semifinal: 'Semi-Final',
  final: 'Final',
  extra: "X'tra Race",
};

function escapeHtml(str) {
  return String(str || '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));
}

function fmtDate(iso) {
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  return d.toLocaleString('en-GB', {
    year: 'numeric', month: 'short', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hour12: false
  });
}

function renderHero(data) {
  const hero = document.getElementById('hero');
  const pigeons = data.stats?.pigeons ?? 0;
  const countries = data.stats?.countries
    ?? new Set(Object.keys(data.participants || {})).size;
  hero.innerHTML = `
    <h1>${escapeHtml(data.title)}</h1>
    <p>${escapeHtml(data.description || '')}</p>
    <div class="pg-stats">
      <div class="pg-stat"><div class="num">${pigeons.toLocaleString()}</div><span class="lbl">Pigeons</span></div>
      <div class="pg-stat"><div class="num">${countries}</div><span class="lbl">Countries</span></div>
      <div class="pg-stat"><div class="num">${(data.schedule || []).length}</div><span class="lbl">Races</span></div>
    </div>
  `;
}

function renderSchedule(data) {
  const el = document.getElementById('schedule');
  const items = data.schedule || [];
  el.innerHTML = items.map(r => `
    <div class="pg-race-card kind-${escapeHtml(r.kind)}">
      <span class="date">${escapeHtml(fmtDate(r.date))}</span>
      <span class="name">${escapeHtml(r.name)} <span style="color:var(--pg-muted);font-weight:400">· ${escapeHtml(KIND_LABELS[r.kind] || r.kind)}</span></span>
      <span class="meta">${escapeHtml(r.location)}</span>
      <span class="dist">${r.distance_km} km</span>
    </div>
  `).join('');
}

function renderParticipants(data) {
  const el = document.getElementById('participants');
  const entries = Object.entries(data.participants || {})
    .sort((a, b) => b[1] - a[1]);
  if (!entries.length) { el.innerHTML = '<p class="pg-muted">No data.</p>'; return; }
  const max = entries[0][1];
  el.innerHTML = `<div class="pg-bar-list">${entries.map(([code, count]) => `
    <div class="pg-bar-row">
      <span class="code">${escapeHtml(code)}</span>
      <span class="bar"><span style="width:${(count / max * 100).toFixed(1)}%"></span></span>
      <span class="count">${count.toLocaleString()}</span>
    </div>
  `).join('')}</div>`;
}

function renderNews(data) {
  const el = document.getElementById('news');
  const items = (data.news || []).slice().sort((a, b) => (b.date || '').localeCompare(a.date || ''));
  el.innerHTML = items.map(n => `
    <article class="pg-news-card">
      <div class="date">${escapeHtml(n.date || '')}</div>
      <div class="title">${escapeHtml(n.title)}</div>
      <div class="body">${escapeHtml(n.body)}</div>
    </article>
  `).join('');
}

function renderSponsors(data) {
  const el = document.getElementById('sponsors');
  el.innerHTML = (data.sponsors || []).map(s =>
    `<span class="pg-sponsor">${escapeHtml(s)}</span>`
  ).join('');
}

function renderContact(data) {
  const el = document.getElementById('contact');
  const c = data.contact || {};
  const phones = (c.phones || []).map(p =>
    `<a href="tel:${escapeHtml(p.replace(/[^+0-9]/g, ''))}">${escapeHtml(p)}</a>`
  ).join(' · ');
  el.innerHTML = `
    <div>${escapeHtml(c.address || '')}</div>
    <div style="margin-top:0.5rem">${phones}</div>
    <div style="margin-top:0.25rem"><a href="mailto:${escapeHtml(c.email || '')}">${escapeHtml(c.email || '')}</a></div>
  `;
}

async function load() {
  try {
    const res = await fetch('pegion.yml');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const text = await res.text();
    // jsyaml is loaded globally by index.html
    const data = jsyaml.load(text);
    document.title = data.title || 'Pigeon Race';
    document.getElementById('topnav-title').textContent = data.subtitle || data.title || 'PIPR';
    renderHero(data);
    renderSchedule(data);
    renderParticipants(data);
    renderNews(data);
    renderSponsors(data);
    renderContact(data);
  } catch (err) {
    console.error('Failed to load pegion.yml:', err);
    document.getElementById('hero').innerHTML =
      `<p style="color:#f87171">Failed to load data: ${escapeHtml(err.message)}</p>`;
  }
}

load();
