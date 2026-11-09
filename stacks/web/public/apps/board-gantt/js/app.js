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

function setStatus(msg, isErr = false) {
  if (!statusEl) return;
  statusEl.textContent = msg;
  statusEl.style.color = isErr ? '#f87171' : '#64748b';
}

function render(payload) {
  const cards = payload.cards || [];
  cardById = new Map(cards.map((c) => [c.id, c]));
  const tasks = buildTasks(cards);
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
    render({ cards, generated: new Date().toISOString().slice(0, 16).replace('T', ' ') });
  } catch (e) {
    setStatus(`load failed: ${e.message}`, true);
  }
}

document.addEventListener('visibilitychange', () => { if (!document.hidden) load(); });
load();
setInterval(load, POLL_MS);
