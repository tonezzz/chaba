// app.js — bootstrap: fetch cards, build tasks, render chart, poll.
import Gantt from '../vendor/frappe-gantt.es.js';
import { fetchCards } from './data.js';
import { buildTasks } from './tasks.js';
import { makePopup } from './popup.js';
import { groupCards, groupIdOf } from './groups.js';
import { GANTT_OPTIONS, POLL_MS } from './config.js';

const el = document.getElementById('gantt');
const statusEl = document.getElementById('gantt-status');
const filterEl = document.getElementById('project-filter');
const refreshEl = document.getElementById('refresh');
let chart = null;
let cardById = new Map();
let lastStamp = null;
let lastCards = [];
let lastGenerated = null;
const collapsed = new Set(); // header _key values — survives polls/rebuilds

function setStatus(msg, isErr = false) {
  if (!statusEl) return;
  statusEl.textContent = msg;
  statusEl.style.color = isErr ? '#f87171' : '#64748b';
}

// Repopulate the project filter from the groups present in the data.
// Preserves the current selection when it still exists.
function syncFilter(cards) {
  if (!filterEl) return;
  const groups = groupCards(cards);
  const prev = filterEl.value;
  filterEl.innerHTML = '<option value="">all projects</option>';
  for (const g of groups) {
    const opt = document.createElement('option');
    opt.value = g.id;
    opt.textContent = `${g.label} (${g.cards.length})`;
    filterEl.appendChild(opt);
  }
  filterEl.value = groups.some((g) => g.id === prev) ? prev : '';
}

// Clicking a group/sub header bar toggles its fold and rebuilds the chart.
function bindFoldHeaders(tasks) {
  for (const t of tasks) {
    if (!t._key) continue;
    const bar = chart && chart.get_bar(t.id);
    const node = bar && (bar.group || bar.$bar);
    if (!node || typeof node.addEventListener !== 'function') continue;
    node.addEventListener('click', (ev) => {
      ev.stopPropagation();
      if (collapsed.has(t._key)) collapsed.delete(t._key);
      else collapsed.add(t._key);
      render();
    });
  }
}

function render() {
  const sel = filterEl ? filterEl.value : '';
  const cards = sel ? lastCards.filter((c) => groupIdOf(c) === sel) : lastCards;
  cardById = new Map(lastCards.map((c) => [c.id, c]));
  const tasks = buildTasks(cards, new Date(), collapsed);
  if (!tasks.length) {
    setStatus(sel ? `no bars in ${sel}` : 'no project cards in scope');
    el.innerHTML = '';
    return;
  }
  el.innerHTML = '';
  chart = new Gantt(el, tasks, {
    ...GANTT_OPTIONS,
    popup: makePopup(cardById),
  });
  bindFoldHeaders(tasks);
  const ngroups = new Set(tasks.map((t) => t._group).filter(Boolean)).size;
  setStatus(`${tasks.length} bars · ${ngroups} group${ngroups === 1 ? '' : 's'} · updated ${lastGenerated || ''}`);
}

async function load(force = false) {
  try {
    const cards = await fetchCards();
    // cheap change detection: card count + newest updated stamp
    const stamp = `${cards.length}:${Math.max(
      0, ...cards.map((c) => Date.parse(String(c.updated || '').replace(' ', 'T')) || 0))}`;
    if (!force && stamp === lastStamp) return;
    lastStamp = stamp;
    lastCards = cards;
    lastGenerated = new Date().toISOString().slice(0, 16).replace('T', ' ');
    syncFilter(cards);
    render();
  } catch (e) {
    setStatus(`load failed: ${e.message}`, true);
  }
}

if (filterEl) filterEl.addEventListener('change', render);
if (refreshEl) refreshEl.addEventListener('click', () => load(true));
document.addEventListener('visibilitychange', () => { if (!document.hidden) load(); });
load();
setInterval(load, POLL_MS);
