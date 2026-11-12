// diagram.js — live lane diagram for one project group.
// Lanes = project sub-groups (project: parent/child slugs); direct members
// sit in a 'members' lane. Cards are nodes colored by kanban column.
// Renders SVG into a container element; returns {height} for layout.
import { DONE_RECENT_DAYS } from '../../board-gantt/js/config.js';
import { groupOf, groupLabel } from '../../board-gantt/js/groups.js';

const DAY = 86400000;
const VIEW_W = 1040;
const LABEL_W = 190;
const PAD = 16;
const NODE_W = 236, NODE_H = 42, GAP_X = 14, GAP_Y = 12;
const LANE_HEAD_H = 30;
const PER_ROW = Math.floor((VIEW_W - LABEL_W - PAD * 2) / (NODE_W + GAP_X));

const COLUMN_LABEL = {
  backlog: 'backlog', lab: 'lab', doing: 'doing',
  review: 'review', done: 'done',
};

function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, (ch) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
}

function parseDate(s) {
  if (!s) return null;
  const d = new Date(String(s).replace(' ', 'T'));
  return isNaN(d) ? null : d;
}

function inScope(card, now) {
  if (card.column !== 'done') return true;
  const last = parseDate(card.lastAt || card.updated);
  return !last || (now - last) <= DONE_RECENT_DAYS * DAY;
}

// sub-path of a card relative to its group — same rule as board-gantt tasks.js
function subPath(card, groupId) {
  const segs = String(card.project || '').split('/').filter(Boolean);
  return segs[0] === groupId ? segs.slice(1).join('/') : '';
}

function truncate(s, n) {
  s = String(s || '');
  return s.length > n ? s.slice(0, n - 1) + '…' : s;
}

// cards -> ordered lanes: [{key,label,cards}] — 'members' lane first,
// then sub-groups alpha. Only in-scope cards.
export function buildLanes(cards, groupId, now = new Date()) {
  const lanes = new Map();
  const add = (key, label, card) => {
    if (!lanes.has(key)) lanes.set(key, { key, label, cards: [] });
    lanes.get(key).cards.push(card);
  };
  for (const c of cards) {
    if (groupOf(c) !== groupId || !inScope(c, now)) continue;
    const sub = subPath(c, groupId);
    add(sub || '', sub || 'members', c);
  }
  const order = [...lanes.values()].sort((a, b) =>
    (a.key === '' ? -1 : b.key === '' ? 1 : a.key.localeCompare(b.key)));
  for (const l of order) {
    l.cards.sort((a, b) =>
      String(a.lastAt || a.updated || '').localeCompare(String(b.lastAt || b.updated || '')) ||
      a.title.localeCompare(b.title));
  }
  return order;
}

const svgEl = (tag, attrs = {}, parent = null) => {
  const n = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  if (parent) parent.appendChild(n);
  return n;
};
const txt = (parent, x, y, s, attrs = {}) => {
  const t = svgEl('text', { x, y, ...attrs }, parent);
  t.textContent = s;
  return t;
};

// Render one diagram spec into `host`. spec: {group, kind:'lanes'}
// collapsed: Set of lane keys. onPick(card, evt): node click callback.
export function renderDiagram(host, spec, cards, { collapsed = new Set(), onPick } = {}) {
  host.innerHTML = '';
  const lanes = buildLanes(cards, spec.group);
  if (!lanes.length) {
    host.innerHTML = `<div style="color:#64748b;padding:20px">no ${esc(groupLabel(spec.group))} cards in scope</div>`;
    return { height: 0, count: 0 };
  }

  // layout pass — collapsed lanes take only the header band
  let y = 8;
  const placed = lanes.map((lane) => {
    const isCollapsed = collapsed.has(lane.key);
    const rows = isCollapsed ? 0 : Math.ceil(lane.cards.length / PER_ROW);
    const h = LANE_HEAD_H + rows * (NODE_H + GAP_Y) + 10;
    const band = { ...lane, y, h, rows, isCollapsed };
    y += h + 10;
    return band;
  });
  const height = y + 44; // legend strip

  const svg = svgEl('svg', {
    viewBox: `0 0 ${VIEW_W} ${height}`,
    width: '100%', role: 'img',
    'aria-label': `${groupLabel(spec.group)} lane diagram`,
  }, host);
  svgEl('title', {}, svg).textContent = `${groupLabel(spec.group)} lanes`;
  svgEl('rect', { width: '100%', height: '100%', fill: 'var(--paper)' }, svg);

  for (const lane of placed) {
    const g = svgEl('g', {}, svg);
    // lane band
    svgEl('rect', {
      x: PAD, y: lane.y, width: VIEW_W - PAD * 2, height: lane.h - 10,
      rx: 8, fill: 'rgba(148,163,184,0.04)',
    }, g);
    // lane head (click = fold)
    const head = svgEl('g', { class: 'lane-head', 'data-lane': lane.key }, g);
    const arrow = lane.isCollapsed ? '▸' : '▾';
    txt(head, PAD + 10, lane.y + 20, `${arrow} ${esc(lane.label)}`,
      { fill: 'var(--ink)', 'font-size': 12, 'font-weight': 600,
        'font-family': 'system-ui,sans-serif', 'letter-spacing': '0.04em' });
    txt(head, VIEW_W - PAD - 10, lane.y + 20, `${lane.cards.length}`,
      { fill: 'var(--muted)', 'font-size': 10, 'text-anchor': 'end',
        'font-family': 'ui-monospace,monospace' });
    svgEl('line', {
      x1: PAD + 10, y1: lane.y + LANE_HEAD_H - 4, x2: VIEW_W - PAD - 10,
      y2: lane.y + LANE_HEAD_H - 4, stroke: 'var(--hairline)', 'stroke-width': 0.8,
    }, g);
    head.addEventListener('click', () => onPick && onPick({ _laneToggle: lane.key }));
    if (lane.isCollapsed) continue;

    lane.cards.forEach((card, i) => {
      const col = i % PER_ROW, row = Math.floor(i / PER_ROW);
      const nx = PAD + 10 + col * (NODE_W + GAP_X);
      const ny = lane.y + LANE_HEAD_H + row * (NODE_H + GAP_Y);
      const ng = svgEl('g', {
        class: `node col-${card.column || 'backlog'}`, transform: `translate(${nx},${ny})`,
      }, g);
      svgEl('rect', { // opaque mask under accent bar
        x: 0, y: 0, width: NODE_W, height: NODE_H, rx: 6, fill: '#101a30',
      }, ng);
      svgEl('rect', { // left column accent
        x: 0, y: 0, width: 4, height: NODE_H, rx: 2, fill: 'var(--col, #64748b)',
      }, ng);
      svgEl('rect', {
        class: 'node-box', x: 0, y: 0, width: NODE_W, height: NODE_H, rx: 6,
        fill: 'rgba(16,26,48,0.85)', stroke: 'var(--hairline)', 'stroke-width': 1,
      }, ng);
      txt(ng, 14, 18, truncate(card.title, 34), {
        fill: 'var(--ink)', 'font-size': 11, 'font-weight': 600,
        'font-family': 'system-ui,sans-serif',
      });
      txt(ng, 14, 33, `${COLUMN_LABEL[card.column] || card.column} · ${truncate(card.id, 30)}`,
        { fill: 'var(--muted)', 'font-size': 9,
          'font-family': 'ui-monospace,monospace' });
      ng.addEventListener('click', (ev) => onPick && onPick(card, ev));
    });
  }

  // legend strip
  const ly = height - 30;
  svgEl('line', {
    x1: PAD, y1: ly - 8, x2: VIEW_W - PAD, y2: ly - 8,
    stroke: 'var(--hairline)', 'stroke-width': 0.8,
  }, svg);
  txt(svg, PAD, ly + 6, 'LEGEND', {
    fill: 'var(--muted)', 'font-size': 8, 'letter-spacing': '0.14em',
    'font-family': 'ui-monospace,monospace',
  });
  const cols = ['backlog', 'lab', 'doing', 'review', 'done'];
  cols.forEach((c, i) => {
    const lx = PAD + 70 + i * 120;
    svgEl('rect', {
      x: lx, y: ly - 3, width: 10, height: 10, rx: 2,
      fill: {
        backlog: '#64748b', lab: '#8b5cf6', doing: '#0ea5e9',
        review: '#f59e0b', done: '#10b981',
      }[c],
    }, svg);
    txt(svg, lx + 16, ly + 6, c, {
      fill: 'var(--muted)', 'font-size': 9, 'font-family': 'ui-monospace,monospace',
    });
  });

  return { height, count: lanes.reduce((n, l) => n + l.cards.length, 0) };
}
