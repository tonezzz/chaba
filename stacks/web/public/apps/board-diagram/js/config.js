// config.js — diagram registry. Each entry renders into #diagram for the
// currently selected project data. Add a diagram = append one DIAGRAMS row.
export const DIAGRAMS = [
  {
    id: 'adobe-stock-lanes',
    label: 'Adobe Stock — lanes',
    // resolved in diagram.js: project group id + lane mode
    group: 'adobe-stock',
    kind: 'lanes',
  },
  // future diagrams, e.g. other projects or other visual types:
  // { id: 'chaba-ci-lanes', label: 'Chaba CI — lanes', group: 'chaba-ci', kind: 'lanes' },
];

export const CARDS_URL = '/apps/board2/cards.json';
export const POLL_MS = 30_000;
