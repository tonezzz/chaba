(function () {
  function isActive(path, href) {
    if (!href || href === '#') return false;
    if (href === '/') return path === '/';
    return path === href || path.startsWith(href);
  }

  function renderItem(i, path) {
    if (i.children && i.children.length) {
      const anyActive = isActive(path, i.href) || i.children.some(c => isActive(path, c.href));
      return `<div class="relative group h-full flex items-center">
        <a href="${i.href}" class="${anyActive ? 'text-accent font-semibold' : 'text-gray-400 hover:text-white transition'} cursor-pointer h-full flex items-center gap-1">${i.label} <span class="text-[10px]">▾</span></a>
        <div class="absolute left-0 top-full hidden group-hover:block bg-card border border-gray-700 rounded-lg shadow-lg min-w-[8rem] p-1 z-[1100]">
          ${i.children.map(c => `<a href="${c.href}" class="block px-3 py-2 text-sm ${isActive(path, c.href) ? 'text-accent font-semibold' : 'text-gray-300 hover:text-white transition'}">${c.label}</a>`).join('')}
        </div>
      </div>`;
    }
    return `<a href="${i.href}" class="${isActive(path, i.href) ? 'text-accent font-semibold' : i.placeholder ? 'text-gray-500 cursor-not-allowed' : 'text-gray-400 hover:text-white transition'}">${i.label}</a>`;
  }

  function renderNav(items, path) {
    path = path || (typeof window !== 'undefined' ? window.location.pathname : '/');
    return `<nav class="bg-card border-b border-gray-700 sticky top-0 z-[1100] h-12"><div class="max-w-7xl mx-auto px-4 h-full flex items-center justify-between"><a href="/" class="text-lg font-bold text-white">HomeLab</a><div class="hidden md:flex gap-4 text-sm h-full items-center">${(items || []).map(i => renderItem(i, path)).join('')}</div></div></nav>`;
  }

  function renderSubnav(items, path) {
    path = path || (typeof window !== 'undefined' ? window.location.pathname : '/');
    return `<nav class="bg-card border-b border-gray-700 sticky top-12 z-[1000] h-10"><div class="max-w-7xl mx-auto px-4 h-full flex items-center gap-4 text-sm">${(items || []).map(i => `<a href="${i.href}" class="${isActive(path, i.href) ? 'text-accent font-semibold' : 'text-gray-300 hover:text-white transition'}">${i.label}</a>`).join('')}</div></nav>`;
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

  async function load(options = {}) {
    const opts = Object.assign({ url: '/apps/apps.yml', target: 'app-nav', subnav: [], subnavTarget: 'app-subnav' }, options);
    await loadYamlLib();
    const res = await fetch(opts.url);
    const text = await res.text();
    const data = window.jsyaml.load(text);
    const path = window.location.pathname;
    const navEl = document.getElementById(opts.target);
    if (navEl) navEl.innerHTML = renderNav(data.nav, path);
    if (opts.subnav && opts.subnav.length && opts.subnavTarget) {
      const subEl = document.getElementById(opts.subnavTarget);
      if (subEl) subEl.innerHTML = renderSubnav(opts.subnav, path);
    }
  }

  window.ChabaNav = { renderNav, renderSubnav, load };
})();
