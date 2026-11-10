// app.js — bootstrap: fetch cards, render selected diagram, poll.
import { fetchCards } from '../board-gantt/js/data.js';
import { groupLabel } from '../board-gantt/js/groups.js';
import { renderDiagram } from './diagram.js';
import { DIAGRAMS, POLL_MS } from './config.js';

const host = document.getElementById('diagram');
const select = document.getElementById('diagram-select');
const statusEl = document.getElementById('diagram-status');
const popup = document.getElementById('popup');

let cards = [];
let cardById = new Map();
let lastStamp = null;
const collapsedLanes = new Set(); // per diagram id -> Set of lane keys
const laneState = new Map();

function setStatus(msg, isErr = false) {
  if (!statusEl) return;
  statusEl.textContent = msg;
  statusEl.style.color = isErr ? '#f87171' : '#64748b';
}

function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, (ch) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
}

function showPopup(card, ev) {
  const lines = [
    `<div class="pt">${esc(card.title)}</div>`,
    `<div class="ps">${esc(card.id)} · <b>${esc(card.column)}</b>` +
      (card.program ? ` · ${esc(card.program)}` : '') + `</div>`,
  ];
  if (card.project) lines.push(`<div class="pd">project: ${esc(card.project)}</div>`);
  if (card.brief) lines.push(`<div class="pd">${esc(card.brief)}</div>`);
  if (card.firstAt || card.lastAt) {
    lines.push(`<div class="pd">${esc(card.firstAt || '?')} → ${esc(card.lastAt || 'today')}</div>`);
  }
  if (card.lastComm && card.lastComm.text) {
    lines.push(`<div class="pd">last: ${esc(card.lastComm.from || '?')} — ${esc(card.lastComm.text).slice(0, 140)}</div>`);
  }
  popup.innerHTML = lines.join('');
  popup.style.display = 'block';
  const pad = 14;
  const x = Math.min(ev.clientX + pad, window.innerWidth - popup.offsetWidth - 8);
  const y = Math.min(ev.clientY + pad, window.innerHeight - popup.offsetHeight - 8);
  popup.style.left = Math.max(8, x) + 'px';
  popup.style.top = Math.max(8, y) + 'px';
}

function hidePopup() { popup.style.display = 'none'; }

function onPick(payload) {
  // lane-header click -> fold/unfold that lane, then rebuild
  const spec = DIAGRAMS.find((d) => d.id === select.value);
  const set = laneState.get(spec.id) || new Set();
  if (set.has(payload._laneToggle)) set.delete(payload._laneToggle);
  else set.add(payload._laneToggle);
  laneState.set(spec.id, set);
  render();
}

function render() {
  const spec = DIAGRAMS.find((d) => d.id === select.value) || DIAGRAMS[0];
  const collapsed = laneState.get(spec.id) || new Set();
  const result = renderDiagram(host, spec, cards, {
    collapsed,
    onPick: (card, ev) => {
      if (card && card._laneToggle !== undefined) { onPick(card); return; }
      if (card && ev) showPopup(card, ev);
    },
  });
  setStatus(`${spec.label} · ${result.count} cards · ${result.height | 0}px`);
}

async function load() {
  try {
    cards = await fetchCards();
    cardById = new Map(cards.map((c) => [c.id, c]));
    const stamp = `${cards.length}:${Math.max(
      0, ...cards.map((c) => Date.parse(String(c.updated || '').replace(' ', 'T')) || 0))}`;
    if (stamp === lastStamp) return;
    lastStamp = stamp;
    render();
  } catch (e) {
    setStatus(`load failed: ${e.message}`, true);
  }
}

// dropdown
for (const d of DIAGRAMS) {
  const o = document.createElement('option');
  o.value = d.id;
  o.textContent = d.label;
  select.appendChild(o);
}
select.addEventListener('change', render);
document.addEventListener('mousemove', (ev) => {
  if (popup.style.display === 'block') {
    const pad = 14;
    popup.style.left = Math.min(ev.clientX + pad, window.innerWidth - popup.offsetWidth - 8) + 'px';
    popup.style.top = Math.min(ev.clientY + pad, window.innerHeight - popup.offsetHeight - 8) + 'px';
  }
});
document.addEventListener('mouseleave', hidePopup);

load();
setInterval(load, POLL_MS);
