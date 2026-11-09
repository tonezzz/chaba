// config.js — all tunables for the board gantt view.
// Add a project = append one GROUPS entry; the rest of the app is generic.

// Ordered project registry. A card joins the FIRST group whose match()
// returns true. match(card) receives a normalized card (see data.js).
// Membership signals available on a card: c.id, c.title, c.column,
// c.tags (array), c.program, c.project (explicit field/tag value).
export const GROUPS = [
  {
    id: 'adobe-stock',
    label: 'Adobe Stock',
    match: (c) =>
      (c.tags || []).includes('adobe-stock') ||
      c.program === 'adobe-stock' ||
      c.project === 'adobe-stock' ||
      c.id.startsWith('adobe-stock-'),
  },
  // future projects go here — e.g.
  // { id: 'chaba-ci', label: 'Chaba CI',
  //   match: (c) => c.program === 'chaba-ci' || (c.tags||[]).includes('chaba-ci') },
];

// Cards matching no GROUPS entry are not charted (v1: opt-in projects only).

// Column -> gantt progress (0-100) and custom_class suffix.
// custom_class lands on the bar wrapper; css/theme.css colors it.
export const COLUMN_STYLE = {
  backlog: { progress: 0,  cls: 'col-backlog' },
  lab:     { progress: 10, cls: 'col-lab'     },
  doing:   { progress: 50, cls: 'col-doing'   },
  review:  { progress: 75, cls: 'col-review'  },
  done:    { progress: 100, cls: 'col-done'   },
};
export const DEFAULT_COLUMN_STYLE = { progress: 0, cls: 'col-backlog' };

// Scope: chart non-done cards always; done cards only if updated within
// this many days (keeps the SVG light).
export const DONE_RECENT_DAYS = 30;

// Cards-json source — same origin as this page.
export const CARDS_URL = '/apps/board2/cards.json';
export const POLL_MS = 30_000;

// frappe-gantt options (view_modes are built-in: Hour..Year).
export const GANTT_OPTIONS = {
  view_mode: 'Month',
  popup_on: 'click',
  container_height: 'auto',
  bar_height: 28,
  padding: 14,
  language: 'en',
};
