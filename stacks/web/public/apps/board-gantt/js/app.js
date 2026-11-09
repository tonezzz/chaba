// app.js — bootstrap: fetch cards, build rows, render gantt + tree,
// keep them scroll-synced, poll for changes.
import Gantt from '../vendor/frappe-gantt.es.js';
import { fetchCards } from './data.js';
import { buildRows, buildTasks } from './tasks.js';
import { renderTree } from './tree.js';
import { makePopup } from './popup.js';
import { GANTT_OPTIONS, POLL_MS } from './config.js';

const ganttEl = document.getElementById('gantt');
const treeEl = document.getElementById('tree');
const statusEl = document.getElementById('gantt-status');
let chart = null;
let rows = [];
let cardById = new Map();
let lastStamp = null;
let rowOffset = 0; // px from gantt content top to first row (measured)

function setStatus(msg, isErr = false) {
  if (!statusEl) return;
  statusEl.textContent = msg;
  statusEl.style.color = isErr ? '#f87171' : '#64748b';
}

// Reveal a card's bar: scroll the gantt to it and open the popup.
function pickCard(row) {
  if (!chart) return;
  const bar = chart.get_bar(row.task.id);
  if (!bar) return;
  const idx = rows.indexOf(row);
  const container = ganttEl.querySelector('.gantt-container');
  if (container) {
    // vertical: align with the svg row (rowOffset + idx * 42px rows)
    container.scrollTop = Math.max(0, rowOffset + idx * 42 - 60);
    // horizontal: bring the bar into view
    const barX = bar.x != null ? bar.x : 0;
    container.scrollLeft = Math.max(0, barX - container.clientWidth / 3);
  }
  chart.show_popup({
    x: (bar.x || 0) + (bar.width || 0) / 2,
    y: (bar.y || 0) + 14,
    task: bar.task,
    target: bar.$bar,
  });
}

function syncChrome() {
  const container = ganttEl.querySelector('.gantt-container');
  const gh = container && container.querySelector('.grid-header');
  const th = treeEl.querySelector('.tree-head');
  const body = treeEl.querySelector('.tree-body-wrap');
  if (gh && th) th.style.height = gh.offsetHeight + 'px';
  // measure where the first gantt row sits inside the scroll content and
  // pad the tree body by the same amount so rows line up 1:1
  const firstBar = ganttEl.querySelector('.bar-wrapper .bar');
  if (container && gh && body && firstBar) {
    const cRect = container.getBoundingClientRect();
    const bRect = firstBar.getBoundingClientRect();
    // bar top -> row top is -7 (bar is vertically centered in the 42px row)
    rowOffset = (bRect.top - cRect.top) + container.scrollTop - 7 - gh.offsetHeight;
    body.style.paddingTop = Math.max(0, rowOffset) + 'px';
  }
}

function bindScrollSync() {
  const container = ganttEl.querySelector('.gantt-container');
  const body = treeEl.querySelector('.tree-body-wrap');
  if (!container || !body) return;
  container.addEventListener('scroll', () => { body.scrollTop = container.scrollTop; }, { passive: true });
  body.addEventListener('scroll', () => { container.scrollTop = body.scrollTop; }, { passive: true });
}

function render(payload) {
  const cards = payload.cards || [];
  cardById = new Map(cards.map((c) => [c.id, c]));
  rows = buildRows(cards);
  const tasks = rows.map((r) => r.task).filter(Boolean);

  ganttEl.innerHTML = '';
  treeEl.innerHTML = '';
  if (!tasks.length) {
    setStatus('no project cards in scope');
    return;
  }
  chart = new Gantt(ganttEl, tasks, { ...GANTT_OPTIONS, popup: makePopup(cardById) });

  const { wrap, head, body } = renderTree(rows, pickCard);
  treeEl.appendChild(wrap);
  // gantt svg height -> tree scroll range parity
  const svg = ganttEl.querySelector('svg.gantt');
  if (svg) body.style.minHeight = svg.getAttribute('height') + 'px';

  syncChrome();
  bindScrollSync();
  setStatus(`${tasks.length} bars · ${rows.filter(r=>r.kind==='card').length} cards · updated ${payload.generated || ''}`);
}

async function load() {
  try {
    const cards = await fetchCards();
    // cheap change detection: card count + newest updated stamp
    const stamp = `${cards.length}:${Math.max(
      0, ...cards.map((c) => Date.parse(String(c.updated || '').replace(' ', 'T')) || 0))}`;
    if (stamp === lastStamp) return;
    lastStamp = stamp;
    render({ cards, generated: new Date().toISOString().slice(0, 16).replace('T', ' ') });
  } catch (e) {
    setStatus(`load failed: ${e.message}`, true);
  }
}

document.addEventListener('visibilitychange', () => { if (!document.hidden) load(); });
load();
setInterval(load, POLL_MS);
