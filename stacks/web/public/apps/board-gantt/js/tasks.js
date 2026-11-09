// tasks.js — normalized cards -> gantt task list + tree row model.
// buildRows() is the single source of truth for row order; buildTasks()
// and the sidebar tree both consume it so they can never drift apart.
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

// Row model shared by the gantt and the tree sidebar. Each entry:
//   { kind: 'group', group, count, task }   — header row (also a gantt bar)
//   { kind: 'card',  card,  task }          — card row
// task is the frappe-gantt task object (null only if a card lacks dates,
// in which case the row is dropped entirely to keep rows 1:1).
export function buildRows(cards, now = new Date()) {
  const rows = [];
  for (const { group, cards: gcards } of groupCards(cards)) {
    const cardRows = [];
    for (const c of gcards) {
      const task = cardToTask(c, now);
      if (task) cardRows.push({ kind: 'card', card: c, task });
    }
    if (!cardRows.length) continue;
    cardRows.sort((a, b) =>
      a.task.start.localeCompare(b.task.start) || a.task.name.localeCompare(b.task.name));

    const starts = cardRows.map((r) => parseDate(r.task.start)).filter(Boolean);
    const ends = cardRows.map((r) => parseDate(r.task.end)).filter(Boolean);
    const headerTask = starts.length && ends.length ? {
      id: `group-${group.id}`,
      name: `▸ ${groupLabel(group.id)} (${cardRows.length})`,
      start: fmt(new Date(Math.min(...starts))),
      end: fmt(new Date(Math.max(...ends))),
      progress: 0,
      custom_class: 'group-header',
      _group: group.id,
    } : null;

    rows.push({ kind: 'group', group, count: cardRows.length, task: headerTask });
    rows.push(...cardRows);
  }
  return rows;
}

// Flat gantt task list (group headers included, in row order).
export function buildTasks(cards, now = new Date()) {
  return buildRows(cards, now).map((r) => r.task).filter(Boolean);
}
