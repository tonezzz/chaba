// config.js — all tunables for the board gantt view.
//
// Grouping (decided 2026-11-09): rows group by the card's `project: <slug>`
// tag/field (ssot.project-lifecycle.yml convention); slug 'a/b' nests 'b'
// as a sub-group under 'a'. Cards with no project tag fall back to
// PROJECT_ALIASES (legacy matchers, e.g. the bare `adobe-stock` tag that
// predates the project: convention); still unmatched -> 'unfiled'.

export const UNGROUPED_ID = 'unfiled';
export const UNGROUPED_LABEL = 'Unfiled';

// Ordered fallback matchers — consulted ONLY when a card carries no
// explicit project slug. First match wins; the matcher's id becomes the
// group id (and the first slug segment for sub-path purposes).
export const PROJECT_ALIASES = [
  {
    id: 'adobe-stock',
    label: 'Adobe Stock',
    match: (c) =>
      (c.tags || []).includes('adobe-stock') ||
      c.program === 'adobe-stock' ||
      c.id.startsWith('adobe-stock-'),
  },
  // future aliases go here — e.g.
  // { id: 'chaba-ci', label: 'Chaba CI',
  //   match: (c) => c.program === 'chaba-ci' || (c.tags||[]).includes('chaba-ci') },
];

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
