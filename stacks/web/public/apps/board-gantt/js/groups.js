// groups.js — resolve which project group a card belongs to.
//
// Group id = first segment of the card's project slug ('a/b/c' -> 'a'),
// PROJECT_ALIASES fallback for untagged cards, 'unfiled' last resort.
// Group order: most recently active project first, 'unfiled' always last.
import {
  PROJECT_ALIASES,
  UNGROUPED_ID,
  UNGROUPED_LABEL,
} from './config.js';

const ALIAS_BY_ID = new Map(PROJECT_ALIASES.map((a) => [a.id, a]));

// Full project slug for a card: explicit `project:` slug wins, then the
// first matching legacy alias, else null (-> unfiled).
export function projectSlugOf(card) {
  if (card.project) return card.project;
  for (const a of PROJECT_ALIASES) {
    try {
      if (a.match(card)) return a.id;
    } catch { /* a bad matcher must not kill the chart */ }
  }
  return null;
}

// Group (top-level) id for a card — first slug segment, or 'unfiled'.
export function groupIdOf(card) {
  const slug = projectSlugOf(card);
  if (!slug) return UNGROUPED_ID;
  return slug.split('/')[0] || UNGROUPED_ID;
}

export function groupLabel(id) {
  if (id === UNGROUPED_ID) return UNGROUPED_LABEL;
  const alias = ALIAS_BY_ID.get(id);
  if (alias) return alias.label;
  return id; // dynamic project:<slug> groups label as their slug
}

function lastActivity(card) {
  const t = Date.parse(String(card.lastAt || card.updated || '').replace(' ', 'T'));
  return isNaN(t) ? 0 : t;
}

// cards -> [{id, label, cards}] in display order (recent activity desc,
// unfiled last, label asc tiebreak). Every card lands in exactly one group.
export function groupCards(cards) {
  const buckets = new Map(); // id -> {id, label, cards, latest}
  for (const c of cards) {
    const gid = groupIdOf(c);
    if (!buckets.has(gid)) {
      buckets.set(gid, { id: gid, label: groupLabel(gid), cards: [], latest: 0 });
    }
    const b = buckets.get(gid);
    b.cards.push(c);
    b.latest = Math.max(b.latest, lastActivity(c));
  }
  return [...buckets.values()].sort((a, b) => {
    if (a.id === UNGROUPED_ID) return 1;
    if (b.id === UNGROUPED_ID) return -1;
    return b.latest - a.latest || a.label.localeCompare(b.label);
  });
}
