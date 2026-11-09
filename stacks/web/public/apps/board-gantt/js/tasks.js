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

// Group header row — a zero-progress span covering the group's date range,
// styled as a label via custom_class (see theme.css .group-header).
function groupHeaderTask(group, cards, tasks) {
  const dates = tasks
    .filter((t) => t._group === group.id)
    .flatMap((t) => [parseDate(t.start), parseDate(t.end)])
    .filter(Boolean);
  if (!dates.length) return null;
  const start = new Date(Math.min(...dates));
  const end = new Date(Math.max(...dates));
  return {
    id: `group-${group.id}`,
    name: `▸ ${groupLabel(group.id)} (${cards.length})`,
    start: fmt(start),
    end: fmt(end),
    progress: 0,
    custom_class: 'group-header',
    _group: group.id,
  };
}

// Full task list: per group, a header row then its cards sorted by start.
// `grouped` is the output of groupCards(); `doneDays` override for tests.
export function buildTasks(cards, now = new Date()) {
  const tasks = [];
  for (const { group, cards: gcards } of groupCards(cards)) {
    const cardTasks = gcards
      .map((c) => cardToTask(c, now))
      .filter(Boolean)
      .map((t) => ({ ...t, _group: group.id }))
      .sort((a, b) => a.start.localeCompare(b.start) || a.name.localeCompare(b.name));
    if (!cardTasks.length) continue;
    const header = groupHeaderTask(group, gcards, cardTasks);
    if (header) tasks.push(header);
    tasks.push(...cardTasks);
  }
  return tasks;
}
