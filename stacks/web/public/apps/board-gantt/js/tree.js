// tree.js — left sidebar: project -> card hierarchy, row-aligned with
// the gantt rows (frappe-gantt row height = bar_height + padding = 42px,
// see config.js GANTT_OPTIONS). Scroll-synced by app.js.

const ROW_H = 42; // keep in sync with GANTT_OPTIONS.bar_height + padding

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}

function cardRow(row, onPick) {
  const c = row.card;
  const r = el('div', 'tree-row tree-card');
  r.style.height = ROW_H + 'px';
  r.title = `${c.id} — ${c.column}`;

  const indent = el('div', 'tree-indent');
  indent.appendChild(el('span', 'tree-twig', '└'));
  const body = el('div', 'tree-body');
  body.appendChild(el('div', 'tree-title', c.title));
  body.appendChild(el('div', `tree-col col-${c.column}`, c.column));
  r.append(indent, body);
  r.onclick = () => onPick(row);
  return r;
}

function groupRow(row) {
  const r = el('div', 'tree-row tree-group');
  r.style.height = ROW_H + 'px';
  r.appendChild(el('div', 'tree-group-label', row.task.name));
  return r;
}

// rows = buildRows() output. onPick(row) fires for card rows.
// Returns {body, header} — header is a sticky spacer matched to the
// gantt's .grid-header height at runtime by app.js.
export function renderTree(rows, onPick) {
  const wrap = el('div', 'tree');
  const head = el('div', 'tree-head');
  head.appendChild(el('div', 'tree-head-title', 'PROJECTS'));
  const body = el('div', 'tree-body-wrap');
  for (const row of rows) {
    body.appendChild(row.kind === 'group' ? groupRow(row) : cardRow(row, onPick));
  }
  // trailing slack so scroll ranges match the gantt svg
  body.appendChild(el('div', 'tree-spacer'));
  wrap.append(head, body);
  return { wrap, head, body };
}
