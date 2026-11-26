// data.js — fetch cards.json and normalize card dicts.
import { CARDS_URL } from './config.js';

// Slug normalization for `project: <slug>` values — lowercase, single
// dashes for whitespace, single slashes kept for parent/child nesting.
function normSlug(s) {
  return String(s || '')
    .trim()
    .toLowerCase()
    .replace(/\s+/g, '-')
    .replace(/\/{2,}/g, '/')
    .replace(/^\/+|\/+$/g, '');
}

// Resolve the card's project slug: explicit `project:` field first, then a
// `project:<slug>` / `project: <slug>` tag (ssot.project-lifecycle.yml).
// Returns null when untagged — groups.js decides the fallback.
function projectSlug(c, tags) {
  if (typeof c.project === 'string' && c.project.trim()) {
    const s = normSlug(c.project);
    if (s) return s;
  }
  const hit = tags.find((t) => typeof t === 'string' && /^project\s*:/i.test(t));
  if (hit) {
    const s = normSlug(hit.replace(/^project\s*:\s*/i, ''));
    if (s) return s;
  }
  return null;
}

// Normalize one raw card into the shape the rest of the app consumes.
// Raw card fields come straight from render-board*.py's cards.json.
export function normalizeCard(c) {
  const comms = Array.isArray(c.comms) ? c.comms : [];
  const tags = Array.isArray(c.tags) ? c.tags : [];
  const project = projectSlug(c, tags);
  const times = comms
    .map((m) => m && m.at)
    .filter(Boolean)
    .sort();
  return {
    id: c.id || '',
    title: c.title || c.id || '(untitled)',
    column: c.column || 'backlog',
    program: c.program || null,
    project,
    tags,
    brief: c.brief || '',
    note: c.note || '',
    // activity span (decided 2026-11-09): first comms/claim/created -> last activity
    firstAt: times[0] || (c.claim && c.claim.since) || c.created || null,
    lastAt: times[times.length - 1] || c.updated || c.created || null,
    created: c.created || null,
    updated: c.updated || null,
    commsCount: comms.length,
    lastComm: comms[comms.length - 1] || null,
    raw: c,
  };
}

export async function fetchCards() {
  const r = await fetch(`${CARDS_URL}?t=${Date.now()}`, { cache: 'no-store' });
  if (!r.ok) throw new Error(`cards.json ${r.status}`);
  const payload = await r.json();
  return (payload.cards || []).map(normalizeCard);
}
