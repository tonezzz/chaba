document.addEventListener('DOMContentLoaded', () => {
  loadFocus();
  document.getElementById('btn-refresh').addEventListener('click', loadFocus);
});

async function loadFocus() {
  const container = document.getElementById('content');
  const last = document.getElementById('last-updated');
  container.innerHTML = '<div class="text-slate-400">Loading...</div>';
  try {
    const res = await fetch('/docs/ssot/ssot.focus.current.yml');
    if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);
    const text = await res.text();
    const data = jsyaml.load(text);
    container.innerHTML = '';
    renderSections(container, data);
    last.textContent = 'Updated: ' + new Date().toLocaleString();
  } catch (err) {
    container.innerHTML = `<div class="text-red-400">Error: ${err.message}</div>`;
    last.textContent = 'Error';
  }
}

function renderSections(container, data) {
  if (!data || !data.sections) {
    container.innerHTML = '<div class="text-slate-400">No sections found</div>';
    return;
  }
  data.sections.forEach(section => {
    const sec = document.createElement('section');
    sec.className = 'bg-slate-800 border border-slate-700 rounded p-4';
    const h2 = document.createElement('h2');
    h2.className = 'text-lg font-semibold mb-3 flex items-center gap-2';
    h2.textContent = section.title;
    sec.appendChild(h2);

    if (section.items && section.items.length) {
      section.items.forEach(item => sec.appendChild(renderItem(item)));
    } else {
      const p = document.createElement('p');
      p.className = 'text-slate-500 text-sm italic';
      p.textContent = 'No active items';
      sec.appendChild(p);
    }
    container.appendChild(sec);
  });
}

function renderItem(item) {
  const div = document.createElement('div');
  div.className = 'mb-4 border-l-4 pl-3 ' + priorityBorder(item.priority, item.status);

  const header = document.createElement('div');
  header.className = 'flex items-center gap-2 flex-wrap';
  const meta = [item.branch, item.priority].filter(Boolean).join(' · ');
  header.innerHTML = `<span class="font-semibold">${escapeHtml(item.label)}</span> ${statusBadge(item.status)} <span class="text-xs text-slate-400">${escapeHtml(meta)}</span>`;
  div.appendChild(header);

  if (item.text) {
    const p = document.createElement('p');
    p.className = 'text-slate-300 text-sm mt-1';
    p.textContent = item.text;
    div.appendChild(p);
  }

  if (item.subtasks && item.subtasks.length) {
    const ul = document.createElement('ul');
    ul.className = 'mt-2 space-y-1';
    item.subtasks.forEach(st => {
      const li = document.createElement('li');
      li.className = 'flex items-start gap-2 text-sm text-slate-300';
      li.innerHTML = `${statusBadge(st.status)} <span>${escapeHtml(st.label)}</span>`;
      ul.appendChild(li);
    });
    div.appendChild(ul);
  }

  if (item.request_log && item.request_log.length) {
    const log = document.createElement('details');
    log.className = 'mt-2 text-sm';
    log.innerHTML = '<summary class="cursor-pointer text-slate-400 hover:text-slate-200">Request log</summary>';
    const logDiv = document.createElement('div');
    logDiv.className = 'mt-1 space-y-1 pl-2 border-l-2 border-slate-700';
    item.request_log.forEach(r => {
      const p = document.createElement('p');
      p.className = 'text-slate-400 text-xs';
      p.textContent = `[${r.date}] ${r.matched_to || ''}: ${r.request}`;
      logDiv.appendChild(p);
    });
    log.appendChild(logDiv);
    div.appendChild(log);
  }
  return div;
}

function priorityBorder(priority, status) {
  if (status === 'active') return 'border-sky-500';
  if (priority === 'high') return 'border-red-500';
  if (priority === 'medium') return 'border-yellow-500';
  if (priority === 'low') return 'border-sky-400';
  return 'border-slate-600';
}

function statusBadge(status) {
  const s = (status || 'unknown').toLowerCase();
  const colors = {
    completed: 'bg-green-900 text-green-200 border-green-700',
    in_progress: 'bg-yellow-900 text-yellow-200 border-yellow-700',
    not_started: 'bg-slate-700 text-slate-300 border-slate-600',
    active: 'bg-sky-900 text-sky-200 border-sky-700',
    pending: 'bg-slate-700 text-slate-300 border-slate-600'
  };
  return `<span class="text-xs px-1.5 py-0.5 rounded border ${colors[s] || 'bg-slate-700 text-slate-300 border-slate-600'}">${escapeHtml(status) || 'unknown'}</span>`;
}

function escapeHtml(text) {
  if (text == null) return '';
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
