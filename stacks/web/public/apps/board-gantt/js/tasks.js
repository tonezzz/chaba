// tasks.js — normalized cards -> frappe-gantt task list.
import { COLUMN_STYLE, DEFAULT_COLUMN_STYLE, DONE_RECENT_DAYS } from './config.js';
import { groupCards, groupLabel } from './groups.js';

const DAY = 86400000;

function parseDate(s) {
  if (!s) return null;
  // cards carry 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM' — treat as local time
  const d = new Date(String(s).replace(' ', 'T'));
  return isNaN(d) ? null : d;
}

function fmt(d) {
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

function inScope(card, now) {
  if (card.column !== 'done') return true;
  const last = parseDate(card.lastAt || card.updated);
  return !last || (now - last) <= DONE_RECENT_DAYS * DAY;
}

// One card -> one gantt task. Returns null when the card has no usable dates.
export function cardToTask(card, now = new Date()) {
  if (!inScope(card, now)) return null;
  let start = parseDate(card.firstAt) || parseDate(card.created);
  if (!start) return null;
  let end = parseDate(card.lastAt) || parseDate(card.updated) || new Date();
  if (card.column !== 'done') end = now;              // open cards run to today
  if (end <= start) end = new Date(start.getTime() + DAY);  // min 1-day bar
  const style = COLUMN_STYLE[card.column] || DEFAULT_COLUMN_STYLE;
  return {
    id: `card-${card.id}`,
    name: card.title,
    start: fmt(start),
    end: fmt(end),
    progress: style.progress,
    custom_class: style.cls,
    _card: card.id,
  };
}

// project: slugs nest — 'adobe-stock/foo' folds under the adobe-stock group
// as sub-group 'foo'. Returns the card's sub-path segments relative to the
// group (['foo','bar'] for 'adobe-stock/foo/bar'), [] for direct members.
function subPath(card, groupId) {
  const segs = String(card.project || '').split('/').filter(Boolean);
  return segs[0] === groupId ? segs.slice(1) : [];
}

const INDENT = '\u00A0'.repeat(4); // nbsp run — SVG text collapses plain spaces

// Span (start..end) covering a set of tasks -> header-row task.
// key identifies the fold node ('group:<id>' / 'sub:<gid>/<path>'); the
// app keeps a collapsed Set of these keys across rebuilds.
function spanHeader(id, name, cls, tasks, key) {
  const dates = tasks
    .flatMap((t) => [parseDate(t.start), parseDate(t.end)])
    .filter(Boolean);
  if (!dates.length) return null;
  return {
    id,
    name,
    start: fmt(new Date(Math.min(...dates))),
    end: fmt(new Date(Math.max(...dates))),
    progress: 0,
    custom_class: cls,
    _group: tasks[0] && tasks[0]._group,
    _key: key,
  };
}

const byStart = (a, b) =>
  a.start.localeCompare(b.start) || a.name.localeCompare(b.name);

// Full task list, depth-first: group header, direct cards, then each
// sub-group (header + its cards). Indentation is a name prefix —
// frappe-gantt labels are plain SVG text, so depth shows as leading space.
// `collapsed` is a Set of header _key values; collapsed nodes emit only
// their header row (▸) and skip all descendants.
export function buildTasks(cards, now = new Date(), collapsed = new Set()) {
  const tasks = [];
  for (const { group, cards: gcards } of groupCards(cards)) {
    const cardTasks = gcards
      .map((c) => ({ card: c, task: cardToTask(c, now) }))
      .filter((x) => x.task)
      .map((x) => ({
        ...x.task,
        _group: group.id,
        _sub: subPath(x.card, group.id),
      }))
      .sort(byStart);
    if (!cardTasks.length) continue;

    const gKey = `group:${group.id}`;
    const gCollapsed = collapsed.has(gKey);
    const header = spanHeader(
      `group-${group.id}`,
      `${gCollapsed ? '▸' : '▾'} ${groupLabel(group.id)} (${cardTasks.length})`,
      'group-header', cardTasks, gKey);
    if (header) tasks.push(header);
    if (gCollapsed) continue;

    const direct = cardTasks.filter((t) => !t._sub.length);
    const subs = new Map(); // 'foo/bar' -> [tasks]
    for (const t of cardTasks) {
      if (t._sub.length) {
        const key = t._sub.join('/');
        if (!subs.has(key)) subs.set(key, []);
        subs.get(key).push(t);
      }
    }

    for (const t of direct) tasks.push({ ...t, name: INDENT + t.name });
    for (const [key, list] of [...subs.entries()].sort()) {
      const sKey = `sub:${group.id}/${key}`;
      const sCollapsed = collapsed.has(sKey);
      const subHeader = spanHeader(
        `sub-${group.id}-${key}`,
        `${sCollapsed ? '▸' : '└'} ${key} (${list.length})`,
        'sub-header', list, sKey);
      if (subHeader) tasks.push(subHeader);
      if (sCollapsed) continue;
      for (const t of list) tasks.push({ ...t, name: INDENT + INDENT + t.name });
    }
  }
  return tasks;
}
