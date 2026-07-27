(function () {
  function escapeHtml(str) {
    const s = String(str);
    return s
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/'/g, '&#39;')
      .replace(new RegExp(String.fromCharCode(34), 'g'), '&quot;');
  }

  async function loadYamlLib() {
    if (typeof window !== 'undefined' && window.jsyaml) return;
    return new Promise((resolve, reject) => {
      const s = document.createElement('script');
      s.src = 'https://cdn.jsdelivr.net/npm/js-yaml@4.1.0/dist/js-yaml.min.js';
      s.onload = resolve;
      s.onerror = reject;
      document.head.appendChild(s);
    });
  }

  function renderLinkGrid(section) {
    return `<div class='grid grid-cols-1 md:grid-cols-2 gap-4'>
      ${(section.items || []).map((item) => {
        const tag = item.href ? `<a href='${escapeHtml(item.href)}' class='app-card hover:border-accent transition'>` : `<div class='app-card'>`;
        const close = item.href ? `</a>` : `</div>`;
        return `${tag}
          <h3 class='text-lg font-semibold text-white'>${escapeHtml(item.title)}</h3>
          ${item.description ? `<p class='text-gray-500 text-sm mt-1'>${escapeHtml(item.description)}</p>` : ''}
          ${item.value ? `<code class='block mt-2 text-sm text-accent'>${escapeHtml(item.value)}</code>` : ''}
        ${close}`;
      }).join('')}
    </div>`;
  }

  function renderStats(section) {
    return `<div class='grid grid-cols-1 md:grid-cols-2 gap-4'>
      ${(section.items || []).map((item) => `
        <div class='app-card'>
          <div class='text-sm text-gray-500'>${escapeHtml(item.title)}</div>
          <div class='text-lg font-semibold text-white mt-1'>${escapeHtml(item.value)}</div>
        </div>
      `).join('')}
    </div>`;
  }

  function renderPanels(section) {
    return `<div class='grid grid-cols-1 md:grid-cols-3 gap-4'>
      ${(section.items || []).map((item) => {
        const tag = item.href ? `<a href='${escapeHtml(item.href)}' class='app-card hover:border-accent transition'>` : `<div class='app-card'>`;
        const close = item.href ? `</a>` : `</div>`;
        const icon = item.icon ? `<div class='text-3xl mb-2'>${escapeHtml(item.icon)}</div>` : '';
        return `${tag}
          ${icon}
          <h3 class='text-lg font-semibold text-white'>${escapeHtml(item.title)}</h3>
          ${item.description ? `<p class='text-gray-500 text-sm mt-1'>${escapeHtml(item.description)}</p>` : ''}
        ${close}`;
      }).join('')}
    </div>`;
  }

  function renderList(section) {
    return `<ul class='space-y-1 text-sm text-gray-600'>
      ${(section.items || []).map((item) => {
        const raw = escapeHtml(item.text || item.label);
        const body = item.href
          ? `<a href='${escapeHtml(item.href)}' class='text-accent hover:underline'>${raw}</a>`
          : item.code
            ? `<code class='ov-code'>${raw}</code>`
            : `<span>${raw}</span>`;
        return `<li><strong class='text-gray-400'>${escapeHtml(item.label)}:</strong> ${body}</li>`;
      }).join('')}
    </ul>`;
  }

  function renderTable(section) {
    const headers = (section.headers || []).map((h) => `<th class='px-3 py-2'>${escapeHtml(h)}</th>`).join('');
    const rows = (section.rows || []).map((row) => `
      <tr class='bg-card'>
        ${row.map((c) => `<td class='px-3 py-2'>${escapeHtml(c)}</td>`).join('')}
      </tr>`).join('');
    return `<div class='app-card p-0 overflow-x-auto'>
      <table class='w-full text-sm text-left text-gray-600'>
        <thead class='bg-card text-gray-200 uppercase text-xs'><tr>${headers}</tr></thead>
        <tbody class='divide-y divide-gray-200'>${rows}</tbody>
      </table>
    </div>`;
  }

  function renderTreeItem(item) {
    if (typeof item === 'string') return `<li class='text-gray-600 text-sm py-0.5'>${escapeHtml(item)}</li>`;
    const children = item.children && item.children.length
      ? `<ul style='padding-left:1rem; margin-top:0.25rem;'>${item.children.map(renderTreeItem).join('')}</ul>`
      : '';
    return `<li class='text-gray-600 text-sm py-1'>
      <strong class='text-gray-200 font-medium'>${escapeHtml(item.label)}</strong>
      ${children}
    </li>`;
  }

  function renderTree(section) {
    return `<ul class='space-y-1'>${(section.items || []).map(renderTreeItem).join('')}</ul>`;
  }

  async function renderDynamicPanels(section) {
    const dataUrl = section.dataUrl;
    if (!dataUrl) return '<p class=\'text-red-500\'>Missing dataUrl for dynamic-panels</p>';
    try {
      const res = await fetch(dataUrl);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const payload = await res.json();
      const items = Array.isArray(payload) ? payload : (payload.items || []);
      if (items.length === 0) return '<p class=\'text-gray-500\'>No docs synced yet.</p>';
      const groups = {};
      items.forEach((item) => {
        const g = item.group || 'Ungrouped';
        const s = item.subgroup || 'Ungrouped';
        groups[g] = groups[g] || {};
        groups[g][s] = groups[g][s] || [];
        groups[g][s].push(item);
      });
      return Object.entries(groups).sort(([a], [b]) => a.localeCompare(b)).map(([group, subgroups]) => `
        <div class='mb-6'>
          <h3 class='text-lg font-semibold text-white mb-2'>${escapeHtml(group)}</h3>
          ${Object.entries(subgroups).sort(([a], [b]) => a.localeCompare(b)).map(([subgroup, subItems]) => `
            <div class='mb-4'>
              <h4 class='text-sm font-medium text-gray-500 mb-2'>${escapeHtml(subgroup)}</h4>
              <div class='grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4'>
                ${subItems.map((item) => {
                  const tag = item.href ? `<a href='${escapeHtml(item.href)}' class='app-card hover:border-accent transition'>` : `<div class='app-card'>`;
                  const close = item.href ? `</a>` : `</div>`;
                  return `${tag}
                    <h3 class='text-lg font-semibold text-white'>${escapeHtml(item.title || item.name || 'Untitled')}</h3>
                    ${item.description ? `<p class='text-gray-500 text-sm mt-1'>${escapeHtml(item.description)}</p>` : ''}
                  ${close}`;
                }).join('')}
              </div>
            </div>
          `).join('')}
        </div>
      `).join('');
    } catch (e) {
      return `<p class='text-red-500'>Could not load ${escapeHtml(dataUrl)}: ${escapeHtml(e.message)}</p>`;
    }
  }

  const LAYOUTS = {
    'link-grid': renderLinkGrid,
    'panels': renderPanels,
    'stats': renderStats,
    'list': renderList,
    'table': renderTable,
    'tree': renderTree,
    'dynamic-panels': renderDynamicPanels
  };

  async function init(dataUrl, targetId) {
    await loadYamlLib();
    const res = await fetch(dataUrl);
    const text = await res.text();
    const data = window.jsyaml.load(text);
    document.title = escapeHtml(data.title || 'Overview');

    const target = document.getElementById(targetId);
    if (!target) return;

    const icon = data.icon ? `<div class='text-5xl mb-2'>${escapeHtml(data.icon)}</div>` : '';
    const sectionsHtml = await Promise.all((data.sections || []).map(async (section) => {
      const sectionIcon = section.icon ? `<span class='mr-2'>${escapeHtml(section.icon)}</span>` : '';
      const content = await (LAYOUTS[section.layout] || renderList)(section);
      return `
        <section class='mb-6'>
          <h2 class='text-xl font-semibold mb-2 text-gray-200'>${sectionIcon}${escapeHtml(section.title)}</h2>
          ${content}
        </section>`;
    }));
    target.innerHTML = `${icon}<h1 class='text-3xl font-bold mb-1 text-gray-200'>${escapeHtml(data.title || 'Overview')}</h1>
      <p class='text-gray-500 mb-6'>${escapeHtml(data.subtitle || '')}</p>` + sectionsHtml.join('');
  }

  window.Overview = { init };
})();
