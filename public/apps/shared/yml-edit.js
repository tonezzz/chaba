(function () {
  function escapeHtml(str) {
    return String(str).replace(/[&<>\"']/g, (m) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '\"': '&quot;', "'": '&#39;' }[m]));
  }

  async function fetchText(url) {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    return await res.text();
  }

  function download(filename, text) {
    const blob = new Blob([text], { type: 'application/x-yaml' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  function copyToClipboard(text) {
    if (navigator.clipboard) return navigator.clipboard.writeText(text);
    const ta = document.createElement('textarea');
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
    return Promise.resolve();
  }

  async function trySave(url, text) {
    try {
      const res = await fetch('/__yml-edit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: url, content: text })
      });
      if (!res.ok) throw new Error(await res.text());
      return 'Saved to server.';
    } catch (e) {
      return `Server save not available (${e.message}). Use Copy or Download.`;
    }
  }

  async function loadWinbox() {
    if (window.WinBox) return;
    return new Promise((resolve, reject) => {
      const s = document.createElement('script');
      s.src = 'https://unpkg.com/winbox@0.2.82/dist/winbox.bundle.min.js';
      s.onload = resolve;
      s.onerror = reject;
      document.head.appendChild(s);
    });
  }

  function buildEditor(files, cache) {
    const root = document.createElement('div');
    root.style.height = '100%';
    root.style.display = 'flex';
    root.style.flexDirection = 'column';
    root.innerHTML = `
      <div class='flex justify-between items-center mb-2'>
        <select id='yml-edit-select' class='flex-1 bg-bg text-gray-200 border border-gray-700 rounded px-2 py-1 font-mono text-xs'>
          ${files.map((f, i) => `<option value='${i}'>${escapeHtml(f.name)}</option>`).join('')}
        </select>
      </div>
      <textarea id='yml-edit-area' class='flex-1 min-h-0 bg-bg text-gray-200 border border-gray-700 rounded p-2 font-mono text-xs' spellcheck='false'></textarea>
      <div id='yml-edit-status' class='text-gray-500 mt-1 h-4 text-xs'></div>
      <div class='flex gap-2 mt-2'>
        <button id='yml-edit-save' class='flex-1 bg-accent text-white rounded px-2 py-1 hover:opacity-90'>Save</button>
        <button id='yml-edit-copy' class='flex-1 bg-card border border-gray-700 text-white rounded px-2 py-1 hover:border-accent'>Copy</button>
        <button id='yml-edit-download' class='flex-1 bg-card border border-gray-700 text-white rounded px-2 py-1 hover:border-accent'>DL</button>
      </div>
    `;

    const select = root.querySelector('#yml-edit-select');
    const area = root.querySelector('#yml-edit-area');
    const status = root.querySelector('#yml-edit-status');

    async function load(idx) {
      const f = files[idx];
      if (!(idx in cache)) cache[idx] = await fetchText(f.url);
      area.value = cache[idx];
      status.textContent = '';
    }

    select.addEventListener('change', () => load(select.value));
    area.addEventListener('input', () => { cache[select.value] = area.value; });

    root.querySelector('#yml-edit-copy').addEventListener('click', async () => {
      await copyToClipboard(area.value);
      status.textContent = 'Copied to clipboard.';
    });
    root.querySelector('#yml-edit-download').addEventListener('click', () => {
      download(files[select.value].name, area.value);
      status.textContent = 'Downloaded.';
    });
    root.querySelector('#yml-edit-save').addEventListener('click', async () => {
      status.textContent = 'Saving...';
      const msg = await trySave(files[select.value].url, area.value);
      status.textContent = msg;
    });

    load(0);
    return root;
  }

  async function init() {
    const links = Array.from(document.querySelectorAll('link[rel=yaml-source]'));
    if (!links.length) return;

    const files = links.map((l) => ({
      url: l.getAttribute('href'),
      name: l.getAttribute('data-name') || l.getAttribute('href').split('/').pop() || l.getAttribute('href')
    }));
    const cache = {};

    const menu = document.createElement('div');
    menu.id = 'yml-edit';
    menu.className = 'fixed top-4 right-4 z-50 bg-card border border-gray-700 rounded-lg shadow-lg p-2 flex gap-2';
    menu.innerHTML = `
      <button id='yml-edit-toggle' class='text-white hover:text-accent text-sm px-2 py-1 transition'>
        Edit YAML
      </button>
    `;
    document.body.appendChild(menu);

    let win = null;
    menu.querySelector('#yml-edit-toggle').addEventListener('click', async () => {
      await loadWinbox();
      if (win) { win.focus(); return; }
      const root = buildEditor(files, cache);
      win = new WinBox('YAML Editor', {
        mount: root,
        width: 500,
        height: 450,
        x: 'right',
        y: 70,
        minwidth: 300,
        minheight: 250,
        onclose: function() { win = null; }
      });
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
