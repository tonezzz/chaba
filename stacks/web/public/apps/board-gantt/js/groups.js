// groups.js — resolve which project group a card belongs to.
import { GROUPS } from './config.js';

const BY_ID = new Map(GROUPS.map((g) => [g.id, g]));

// First matching group wins (GROUPS order = display order).
export function groupOf(card) {
  for (const g of GROUPS) {
    try {
      if (g.match(card)) return g.id;
    } catch { /* a bad matcher must not kill the chart */ }
  }
  return null;
}

export function groupLabel(id) {
  return (BY_ID.get(id) || { label: id }).label;
}

// cards -> {groupId: [cards]} preserving GROUPS order; empty groups dropped.
export function groupCards(cards) {
  const buckets = new Map(GROUPS.map((g) => [g.id, []]));
  for (const c of cards) {
    const gid = groupOf(c);
    if (gid) buckets.get(gid).push(c);
  }
  return GROUPS.map((g) => ({ group: g, cards: buckets.get(g.id) }))
    .filter((b) => b.cards.length > 0);
}
