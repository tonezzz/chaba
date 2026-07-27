(function () {
  function escapeHtml(str) {
    return String(str).replace(/[&<>"']/g, (m) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[m]));
  }

  function loadYamlLib() {
    if (typeof window !== 'undefined' && window.jsyaml) return Promise.resolve();
    return new Promise((resolve, reject) => {
      const s = document.createElement('script');
      s.src = 'https://cdn.jsdelivr.net/npm/js-yaml@4.1.0/dist/js-yaml.min.js';
      s.onload = resolve;
      s.onerror = reject;
      document.head.appendChild(s);
    });
  }

  function renderGrid2(section) {
    return `<div class="grid grid-cols-1 md:grid-cols-2 gap-4">
      ${section.items.map((item) => {
        const tag = item.href
          ? `<a href="${escapeHtml(item.href)}" class="app-card">`
          : `<div class="app-card">`;
        const close = item.href ? `</a>` : `</div>`;
        return `${tag}
          <h3 class="text-base font-semibold text-white">${escapeHtml(item.title)}</h3>
          ${item.description ? `<p class="text-gray-500 text-sm mt-1">${escapeHtml(item.description)}</p>` : ''}
          ${item.value ? `<code class="block mt-2 text-sm text-accent">${escapeHtml(item.value)}</code>` : ''}
        ${close}`;
      }).join('')}
    </div>`;
  }

  function renderList(section) {
    return `<ul class="space-y-1 text-sm text-gray-600">
      ${section.items.map((item) => {
        const raw = escapeHtml(item.text || item.label);
        const body = item.href
          ? `<a href="${escapeHtml(item.href)}" class="text-accent hover:underline">${raw}</a>`
          : item.code
            ? `<code class="docs-code">${raw}</code>`
            : `<span>${raw}</span>`;
        return `<li><strong class="text-white">${escapeHtml(item.label)}:</strong> ${body}</li>`;
      }).join('')}
    </ul>`;
  }

  function renderTable(section) {
    const headers = section.headers.map((h) => `<th class="px-3 py-2">${escapeHtml(h)}</th>`).join('');
    const rows = section.rows.map((row) => `
      <tr class="bg-card">
        ${row.map((c) => `<td class="px-3 py-2">${escapeHtml(c)}</td>`).join('')}
      </tr>`).join('');
    return `<div class="app-card p-0 overflow-x-auto">
      <table class="w-full text-sm text-left text-gray-600">
        <thead class="bg-card text-gray-200 uppercase text-xs"><tr>${headers}</tr></thead>
        <tbody class="divide-y divide-gray-200">${rows}</tbody>
      </table>
    </div>`;
  }

  function renderAppsPlaceholder() {
    return `<div id="docs-apps-grid" class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4"></div>`;
  }

  async function renderApps() {
    const res = await fetch('/apps/apps.yml');
    const text = await res.text();
    const data = window.jsyaml.load(text);
    const apps = (data.apps || []).filter((a) => !a.placeholder);
    const html = apps.map((a) => `
      <a href="${escapeHtml(a.href)}" class="app-card hover:border-accent transition">
        <div class="text-2xl mb-1">${escapeHtml(a.icon || '')}</div>
        <h3 class="font-semibold text-white">${escapeHtml(a.title)}</h3>
        <p class="text-gray-500 text-sm mt-1">${escapeHtml(a.description)}</p>
      </a>`).join('');
    const el = document.getElementById('docs-apps-grid');
    if (el) el.innerHTML = html;
  }

  function renderRunbook(section) {
    const field = (label, value) => value ? `<div class="mb-2"><strong class="text-gray-400 text-xs uppercase">${escapeHtml(label)}</strong><br><span class="text-gray-600">${escapeHtml(value)}</span></div>` : '';
    const codeBlock = (label, value) => value ? `<div class="mb-2"><strong class="text-gray-400 text-xs uppercase">${escapeHtml(label)}</strong><div class="docs-code" style="white-space: pre-wrap;">${escapeHtml(value)}</div></div>` : '';
    return `<div class="space-y-4">
      ${(section.items || []).map((item) => `
        <div class="app-card">
          <h3 class="text-base font-semibold text-white mb-1">${escapeHtml(item.service || 'Runbook')}</h3>
          ${item.description ? `<p class="text-gray-500 text-sm mb-3">${escapeHtml(item.description)}</p>` : ''}
          ${field('Stack', item.stack)}
          ${field('Env file', item.env_file)}
          ${codeBlock('Start command', item.start_command)}
          ${field('Prerequisites', item.pre_requisites)}
          ${field('Depends on', item.depends_on)}
          ${field('Health check', item.health_check)}
          ${field('Backup paths', item.backup_paths)}
          ${field('Last verified', item.last_verified)}
        </div>
      `).join('')}
    </div>`;
  }

  const LAYOUTS = {
    'grid-2': renderGrid2,
    list: renderList,
    table: renderTable,
    apps: renderAppsPlaceholder,
    runbook: renderRunbook
  };

  async function init(dataUrl, targetId) {
    await loadYamlLib();
    const res = await fetch(dataUrl);
    const text = await res.text();
    const data = window.jsyaml.load(text);
    document.title = escapeHtml(data.title || 'Docs');

    const target = document.getElementById(targetId);
    if (!target) return;

    const icon = data.icon ? `<div class="text-5xl mb-2">${escapeHtml(data.icon)}</div>` : '';
    target.innerHTML = `${icon}<h1 class="text-3xl font-bold mb-1 text-gray-200">${escapeHtml(data.title || 'Docs')}</h1>
      <p class="text-gray-500 mb-6">${escapeHtml(data.subtitle || '')}</p>` +
      (data.sections || []).map((section) => {
        const sectionIcon = section.icon ? `<span class="mr-2">${escapeHtml(section.icon)}</span>` : '';
        return `
        <section class="mb-6">
          <h2 class="text-xl font-semibold mb-2 text-gray-200">${sectionIcon}${escapeHtml(section.title)}</h2>
          ${(LAYOUTS[section.layout] || renderList)(section)}
        </section>`;
      }).join('');

    const hasApps = (data.sections || []).some((s) => s.layout === 'apps');
    if (hasApps) await renderApps();
  }

  window.Docs = { init };
})();
