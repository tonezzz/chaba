let allCaptures = [];

function tagColor(tag) {
  if (tag === 'local') return 'bg-emerald-900/50 text-emerald-300 border border-emerald-800';
  if (tag === 'external') return 'bg-purple-900/50 text-purple-300 border border-purple-800';
  return 'bg-gray-800 text-gray-300';
}

function buildTagSelect(captures) {
  const select = document.getElementById('tag-filter');
  const tags = Array.from(new Set(captures.flatMap(c => c.tags || []))).sort();
  tags.forEach(tag => {
    const opt = document.createElement('option');
    opt.value = tag;
    opt.textContent = tag;
    select.appendChild(opt);
  });
}

function openModal(item) {
  document.getElementById('modal-title').textContent = item.title;
  document.getElementById('modal-image').src = item.thumbnail;
  document.getElementById('modal-image').alt = item.title;
  document.getElementById('modal-description').textContent = item.description;
  document.getElementById('modal-figma').href = item.figmaUrl;
  document.getElementById('modal-source').href = item.sourceUrl;

  const generated = document.getElementById('modal-generated');
  if (item.generated) {
    generated.classList.remove('hidden');
    document.getElementById('modal-generated-react').href = item.generated.react;
    document.getElementById('modal-generated-preview').href = item.generated.preview;
  } else {
    generated.classList.add('hidden');
  }

  const tags = document.getElementById('modal-tags');
  tags.innerHTML = '';
  (item.tags || []).forEach(tag => {
    const span = document.createElement('span');
    span.className = `px-2 py-1 rounded text-xs ${tagColor(tag)}`;
    span.textContent = tag;
    tags.appendChild(span);
  });
  if (item.selector) {
    const span = document.createElement('span');
    span.className = 'px-2 py-1 rounded text-xs bg-gray-800 text-gray-300';
    span.textContent = `selector: ${item.selector}`;
    tags.appendChild(span);
  }
  if (item.capturedAt) {
    const span = document.createElement('span');
    span.className = 'px-2 py-1 rounded text-xs bg-gray-800 text-gray-300';
    span.textContent = item.capturedAt;
    tags.appendChild(span);
  }

  document.getElementById('modal').classList.remove('hidden');
  document.body.classList.add('modal-open');
}

function closeModal() {
  document.getElementById('modal').classList.add('hidden');
  document.body.classList.remove('modal-open');
}

function render(captures) {
  const grid = document.getElementById('gallery');
  const empty = document.getElementById('empty');
  grid.innerHTML = '';

  if (captures.length === 0) {
    empty.classList.remove('hidden');
    return;
  }
  empty.classList.add('hidden');

  captures.forEach(item => {
    const card = document.createElement('article');
    card.className = 'bg-card rounded-xl border border-gray-800 overflow-hidden hover:border-cyan-500 transition cursor-pointer group';
    const tags = (item.tags || []).map(tag =>
      `<span class="px-2 py-1 rounded text-xs ${tagColor(tag)}">${tag}</span>`
    ).join('');
    card.innerHTML = `
      <div class="aspect-video bg-gray-900 overflow-hidden">
        <img src="${item.thumbnail}" alt="${item.title}" class="w-full h-full object-cover group-hover:scale-105 transition duration-300">
      </div>
      <div class="p-4">
        <h2 class="text-lg font-semibold text-gray-100">${item.title}</h2>
        <p class="text-sm text-gray-400 mt-1 line-clamp-2">${item.description}</p>
        <div class="mt-3 flex flex-wrap gap-2">${tags}</div>
      </div>
    `;
    card.addEventListener('click', () => openModal(item));
    grid.appendChild(card);
  });
}

function applyFilters() {
  const q = document.getElementById('search').value.trim().toLowerCase();
  const tag = document.getElementById('tag-filter').value;
  const filtered = allCaptures.filter(item => {
    const matchesSearch = !q ||
      item.title.toLowerCase().includes(q) ||
      item.description.toLowerCase().includes(q) ||
      (item.tags || []).some(t => t.toLowerCase().includes(q));
    const matchesTag = !tag || (item.tags || []).includes(tag);
    return matchesSearch && matchesTag;
  });
  render(filtered);
}

async function init() {
  const res = await fetch('captures.json');
  allCaptures = await res.json();
  buildTagSelect(allCaptures);
  render(allCaptures);

  document.getElementById('search').addEventListener('input', applyFilters);
  document.getElementById('tag-filter').addEventListener('change', applyFilters);
  document.getElementById('modal-close').addEventListener('click', closeModal);
  document.getElementById('modal').addEventListener('click', (e) => {
    if (e.target.id === 'modal') closeModal();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeModal();
  });
}

document.addEventListener('DOMContentLoaded', init);
