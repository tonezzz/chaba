// app.js — bootstrap: fetch cards, render selected diagram, poll.
// CONTROL (card board-diagram-lanes-view): node click opens an action
// panel — claim / move / finish post to board-api /action, same-origin
// so the edge injects the caller identity exactly like board2 (tailnet
// Tailscale-User-Login on the tailnet front, X-Board-Edge-Key +
// Cf-Access-Authenticated-User-Email on the CF-Access vhost). Lane heads
// carry a claim-queued batch button when the lane holds queued cards.
import { fetchCards } from '../../board-gantt/js/data.js';
import { renderDiagram, actOf } from './diagram.js';
import { DIAGRAMS, POLL_MS } from './config.js';

const API = '/apps/board-api';
// do:claim/do:finish need a host; 'tony' marks a human claim (canon_host
// compares case/dash-insensitive, so claim+finish pair under one name).
const CLAIM_HOST = 'tony';
// board-api COLUMNS — 'lab' is deliberately absent: lab has its own
// promote/retire flow and do_move refuses it.
const MOVE_COLUMNS = ['backlog', 'doing', 'review', 'done'];

const host = document.getElementById('diagram');
const select = document.getElementById('diagram-select');
const statusEl = document.getElementById('diagram-status');
const popup = document.getElementById('popup');

let cards = [];
let lastStamp = null;
const laneState = new Map(); // diagram id -> Set of collapsed lane keys

function setStatus(msg, isErr = false) {
  if (!statusEl) return;
  statusEl.textContent = msg;
  statusEl.style.color = isErr ? '#f87171' : '#64748b';
}

function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, (ch) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
}

function canonHost(s) {
  return String(s || '').trim().toLowerCase().replace(/-/g, '_');
}

// board2's api() shape: 60s timeout (the write flock can hold across a
// kanban-commit pull+push), JSON body, {ok,message} | {error}.
async function apiAction(body) {
  try {
    const r = await fetch(API + '/action', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(60000),
    });
    return await r.json();
  } catch (e) {
    return { ok: false, error: String(e) };
  }
}

// Client-side mirror of do_claim's hard gates — the server stays
// authoritative; this only decides whether the button looks live.
function claimGate(card) {
  const a = actOf(card);
  if (a.status !== 'queued')
    return `not queued (action.status=${a.status || 'idle'})`;
  if (['manual'].includes(a.lane) || ['manual'].includes(a.executor) ||
      ['manual'].includes(a.type))
    return 'manual card — move it to doing instead';
  return '';
}

function runningByMe(card) {
  const a = actOf(card);
  return a.status === 'running' && canonHost(a.runner) === canonHost(CLAIM_HOST);
}

function closePanel() {
  popup.style.display = 'none';
  popup.innerHTML = '';
}

function report(j) {
  const m = popup.querySelector('.pmsg');
  if (m) m.textContent = j.ok ? `✓ ${j.message || 'ok'}` : `✗ ${j.error || 'refused'}`;
  if (j.ok) {
    // board-api re-renders cards.json async; poll catches stragglers
    setTimeout(load, 1500);
    setTimeout(load, 6000);
  }
}

async function doClaim(id) {
  report(await apiAction({ id, do: 'claim', host: CLAIM_HOST }));
}

async function doMove(id, column) {
  report(await apiAction({ id, do: 'move', column }));
}

async function doFinish(card) {
  // claim/finish pair for cards this page claimed; everyone else gets the
  // human close verb (column->done, merge-guarded) — same as board2.
  const body = runningByMe(card)
    ? { id: card.id, do: 'finish', host: CLAIM_HOST, ok: true,
        result: 'finished via board-diagram' }
    : { id: card.id, do: 'close' };
  report(await apiAction(body));
}

function openPanel(card, x, y) {
  const a = actOf(card);
  const col = card.column || 'backlog';
  const gate = claimGate(card);
  const lines = [
    `<div class="pp-head"><span class="pt">${esc(card.title)}</span>`,
    `<button class="px" title="close">✕</button></div>`,
    `<div class="ps">${esc(card.id)} · <b>${esc(col)}</b>` +
      (a.status && a.status !== 'idle' ? ` · ${esc(a.status)}` : '') +
      (card.program ? ` · ${esc(card.program)}` : '') + `</div>`,
  ];
  if (card.project) lines.push(`<div class="pd">project: ${esc(card.project)}</div>`);
  if (card.brief) lines.push(`<div class="pd brief">${esc(card.brief)}</div>`);
  if (card.note) lines.push(`<div class="pd">${esc(card.note).slice(0, 300)}</div>`);
  if (card.firstAt || card.lastAt) {
    lines.push(`<div class="pd">${esc(card.firstAt || '?')} → ${esc(card.lastAt || 'today')}</div>`);
  }
  if (card.lastComm && card.lastComm.text) {
    lines.push(`<div class="pd">last: ${esc(card.lastComm.from || '?')} — ${esc(card.lastComm.text).slice(0, 140)}</div>`);
  }
  lines.push(
    `<div class="pa">` +
      `<button class="pb" data-a="claim" ${gate ? 'disabled' : ''} ` +
        `title="${esc(gate || `claim for host '${CLAIM_HOST}' (do:claim)`)}">▶ claim</button>` +
      `<select class="pmv" title="move to column (do:move)">` +
        MOVE_COLUMNS.map((m) =>
          `<option value="${m}" ${m === col ? 'selected' : ''}>${m === col ? '• ' : ''}${m}</option>`).join('') +
      `</select>` +
      `<button class="pb fin" data-a="finish" ${col === 'done' ? 'disabled' : ''} ` +
        `title="${runningByMe(card) ? 'finish claim (do:finish)' : 'close card (do:close)'}">✓ finish</button>` +
    `</div><div class="pmsg"></div>`);
  popup.innerHTML = lines.join('');
  popup.style.display = 'block';
  const w = popup.offsetWidth, h = popup.offsetHeight;
  popup.style.left = Math.min(Math.max(8, x + 14), window.innerWidth - w - 8) + 'px';
  popup.style.top = Math.min(Math.max(8, y + 14), window.innerHeight - h - 8) + 'px';

  popup.querySelector('.px').onclick = closePanel;
  popup.querySelector('.pmv').onchange = (e) => {
    if (e.target.value && e.target.value !== col) doMove(card.id, e.target.value);
  };
  popup.querySelector('[data-a="claim"]').onclick = () => doClaim(card.id);
  popup.querySelector('[data-a="finish"]').onclick = () => doFinish(card);
}

async function claimLane(lane) {
  const ids = lane.cards.filter((c) => actOf(c).status === 'queued').map((c) => c.id);
  if (!ids.length) return;
  if (!confirm(`Claim ${ids.length} queued card(s) in "${lane.label}"?\n` +
               `They go running under host '${CLAIM_HOST}' — finish them here or they stall.`)) return;
  setStatus(`claiming ${ids.length} queued in ${lane.label}…`);
  let okN = 0;
  const errs = [];
  for (const id of ids) {
    const j = await apiAction({ id, do: 'claim', host: CLAIM_HOST });
    if (j.ok) okN++;
    else errs.push(`${id}: ${j.error || 'refused'}`);
    setStatus(`claiming ${okN + errs.length}/${ids.length}…`);
  }
  setStatus(`lane claim: ${okN}/${ids.length} ok` +
            (errs.length ? ` — ${errs[0]}` : ''), errs.length > 0);
  setTimeout(load, 1500);
  setTimeout(load, 6000);
}

function toggleLane(diagramId, key) {
  const set = laneState.get(diagramId) || new Set();
  if (set.has(key)) set.delete(key); else set.add(key);
  laneState.set(diagramId, set);
  render();
}

function render() {
  const spec = DIAGRAMS.find((d) => d.id === select.value) || DIAGRAMS[0];
  const collapsed = laneState.get(spec.id) || new Set();
  const result = renderDiagram(host, spec, cards, {
    collapsed,
    onPick: (card, ev) => {
      if (card && card._laneToggle !== undefined) { toggleLane(spec.id, card._laneToggle); return; }
      if (card && ev) openPanel(card, ev.clientX, ev.clientY);
    },
    onLaneAction: (lane) => claimLane(lane),
  });
  setStatus(`${spec.label} · ${result.count} cards · ${result.height | 0}px`);
}

async function load() {
  try {
    cards = await fetchCards();
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

// click on empty diagram space dismisses the action panel
document.addEventListener('click', (ev) => {
  if (popup.style.display !== 'block') return;
  if (popup.contains(ev.target)) return;
  const t = ev.target;
  if (t && t.closest && t.closest('.node, .lane-head, .lane-act')) return;
  closePanel();
});
document.addEventListener('keydown', (ev) => {
  if (ev.key === 'Escape') closePanel();
});

load();
setInterval(load, POLL_MS);
