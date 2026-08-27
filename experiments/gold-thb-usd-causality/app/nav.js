document.addEventListener('DOMContentLoaded', () => {
  const pages = [
    { href: 'index.html', label: 'Hub' },
    { href: 'vector-search-ideas.html', label: 'Vector-search ideas' },
    { href: 'vector-analysis-ideas.html', label: 'Vector-analysis ideas' },
    { href: 'thb-settlement.html', label: 'THB settlement' },
    { href: 'conclusion.html', label: 'Conclusion' },
  ];
  const current = window.location.pathname.split('/').pop() || 'index.html';
  const nav = document.createElement('nav');
  nav.style.cssText = 'margin: 0 0 1.5rem 0; padding: 0.5rem 0; border-bottom: 1px solid #dee2e6;';
  nav.innerHTML = `<a href="index.html" style="font-weight: 700; color: #212529; text-decoration: none; margin-right: 1rem;">Gold/THB/USD</a>` +
    pages.map(p => {
      const active = p.href === current || (p.href === 'index.html' && current === '');
      return `<a href="${p.href}" style="margin-right: 0.75rem; color: ${active ? '#0d6efd' : '#6c757d'}; font-weight: ${active ? '600' : '400'}; text-decoration: none;">${p.label}</a>`;
    }).join('');
  const target = document.querySelector('h1');
  if (target) target.parentNode.insertBefore(nav, target);
});
