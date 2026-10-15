# dispatch-outcome: board2 Planka-style column reskin

## What changed

`scripts/render-board2.py` rewritten in the view layer only — board1,
the cards.json payload, and board-api are untouched.

- **5 columns side-by-side** (lab/backlog/doing/review/done), each a
  self-scrolling Planka-style lane; tab navigation removed entirely.
  Lab stays a virtual lane: lab cards appear there sorted by review_by
  AND in their real column (same semantics the tabs had), with the real
  column shown as a chip.
- **Zoom -/+** in the nav cycles card density compact|normal|full via a
  class on the board container (`d-compact`/`d-normal`/`d-full`),
  persisted in `b2-density`. compact = title + ❓/💬 affordances only;
  normal = + all label chips; full = + first line of brief.
- **Tight card rows**: title + chips (id, priority, lab, `❓n` open
  requests/asks, `💬n` comments, check-fail) — nothing else.
- **Drag & drop**: cards are `draggable`; a drop on backlog/doing/
  review/done POSTs `/apps/board-api/action {id, do:'move', column}`.
  Lab is not a drop target (virtual lane — dimmed during drags).
- **Modal card view**: click opens an overlay (backdrop/Esc/✕ to close)
  with the full previous detail pane — actions, move select, brief, lab
  fields, asks/requests, comms, comment box. `#card=<id>` deep-link
  still works; the modal re-renders live on each 10s poll, preserving
  scroll position and a half-typed comment.
- **Kept**: live poll + in-place column diff (`just-moved` flash), doing
  column pulse on its count chip, Needs-Tony band (controls shared with
  the modal via `wireReq`), event ticker, live-dot, per-column
  automation collapse groups.
- **Filter** moved into the nav; single query filters all columns at
  once, counts show `vis/total` while filtering.
- Template changed from f-string to raw string + `__POLL_SECONDS__`
  placeholder, so JS braces/escapes pass through verbatim.

## Result

- `python3 scripts/render-board2.py` regenerates OK (721 cards).
- Emitted `<script>` passes `node --check`.
- Headless-Chrome DOM test (fetch spy + synthetic drag/click events):
  8/8 PASS — 5 cols render, modal open/title/Esc-close, zoom
  full+compact, drop posts `move` with correct id/column, lab column
  rejects drops.
- Only `render-board2.py` changed; `index.html`/`cards.json` are
  gitignored artifacts. Trail: `docs/ssot/jobs/kanban/2026-10-15-board2-column-reskin.yml`.

## How to verify

1. Re-render and open board2 — five columns side-by-side, no tabs.
2. Click a card → modal overlay opens; Esc/backdrop/✕ closes.
3. Click −/+ in nav → density cycles compact/normal/full (reload keeps it).
4. Drag a card to another column → toast "moved → X", row flashes.
   Dragging onto Lab does nothing.
5. Move a card elsewhere (classic board/API) → within ≤10s it jumps
   columns on board2 with a blue flash, no reload.
6. Remaining scope note: Planka lab on idc02:8301 can be torn down
   (`podman-compose down -v ~/planka-lab`) once Tony confirms.
