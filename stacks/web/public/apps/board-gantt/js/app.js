// app.js — bootstrap: fetch cards, build tasks, render chart, poll.
import Gantt from '../vendor/frappe-gantt.es.js';
import { fetchCards } from './data.js';
import { buildTasks } from './tasks.js';
import { makePopup } from './popup.js';
import { GANTT_OPTIONS, POLL_MS } from './config.js';

const el = document.getElementById('gantt');
const statusEl = document.getElementById('gantt-status');
let chart = null;
let cardById = new Map();
let lastGenerated = null;
let lastPayload = null;
const collapsed = new Set(); // header _key values — survives polls/rebuilds
let tasks = [];

function setStatus(msg, isErr = false) {
  if (!statusEl) return;
  statusEl.textContent = msg;
  statusEl.style.color = isErr ? '#f87171' : '#64748b';
}

// Clicking a group/sub header bar toggles its fold and rebuilds the chart.
function bindFoldHeaders() {
  for (const t of tasks) {
    if (!t._key) continue;
    const bar = chart && chart.get_bar(t.id);
    const node = bar && (bar.group || bar.$bar);
    if (!node || typeof node.addEventListener !== 'function') continue;
    node.addEventListener('click', (ev) => {
      ev.stopPropagation();
      if (collapsed.has(t._key)) collapsed.delete(t._key);
      else collapsed.add(t._key);
      if (lastPayload) render(lastPayload);
    });
  }
}

function render(payload) {
  const cards = payload.cards || [];
  cardById = new Map(cards.map((c) => [c.id, c]));
  tasks = buildTasks(cards, new Date(), collapsed);
  if (!tasks.length) {
    setStatus('no project cards in scope');
    el.innerHTML = '';
    return;
  }
  el.innerHTML = '';
  chart = new Gantt(el, tasks, {
    ...GANTT_OPTIONS,
    popup: makePopup(cardById),
  });
  bindFoldHeaders();
  setStatus(`${tasks.length} bars · updated ${payload.generated || ''}`);
}

async function load() {
  try {
    const cards = await fetchCards();
    // cheap change detection: card count + newest updated stamp
    const stamp = `${cards.length}:${Math.max(
      0, ...cards.map((c) => Date.parse(String(c.updated || '').replace(' ', 'T')) || 0))}`;
    if (stamp === lastGenerated) return;
    lastGenerated = stamp;
    lastPayload = { cards, generated: new Date().toISOString().slice(0, 16).replace('T', ' ') };
    render(lastPayload);
  } catch (e) {
    setStatus(`load failed: ${e.message}`, true);
  }
}

document.addEventListener('visibilitychange', () => { if (!document.hidden) load(); });
load();
setInterval(load, POLL_MS);
