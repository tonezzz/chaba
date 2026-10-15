# dispatch-outcome: render-board2 living board MVP

## What changed

`scripts/render-board2.py` (+61/-7) — all presentation-layer, zero backend changes:

1. **Live poll + in-place column diff** — `POLL_SECONDS` 30 → 10. `load()` snapshots
   `card → column` before swapping `DATA`; cards that entered the board or changed
   column land in `movedIn` and their rows render with `.just-moved` (1.8s blue
   flash) + a `⇄ <column>` badge. No page reload; flags reset each poll so tab
   switches inside the window re-flash.
2. **Per-column counters + doing pulse** — the tab counts already serve as
   counters; the Doing tab gains `.doing-hot` (1.6s green ring pulse) whenever its
   count > 0.
3. **Floating event ticker** — `#ticker` fixed at bottom (26px, "事件流" label).
   `renderTicker()` merges `comms` across all cards (rescued / test-gate / held /
   deployed / comments are all comm lines), sorts desc by `at`, takes 30, scrolls
   via a `translateX(-50%)` seamless loop (content duplicated once). Track DOM only
   rebuilds when the item signature changes so the marquee keeps running between
   polls; duration scales with items (min 30s). Main pane gets `pb-8` so the bar
   never covers rows.
4. **live-dot blip** — nav dot restarts a scale animation each successful poll;
   still goes red on fetch failure.

## Result

- `python3 scripts/render-board2.py` regenerates OK (721 cards).
- Emitted `index.html` has no leftover `{{`/`}}`; extracted `<script>` passes
  `node --check`.
- Generated `index.html`/`cards.json` are gitignored artifacts — the only source
  change is `render-board2.py`; plus trail file
  `docs/ssot/jobs/kanban/2026-10-15-board2-living-board.yml`.

## How to verify

1. Re-render and open board2: `python3 scripts/render-board2.py`, then open the
   board2 page — the bottom ticker should scroll card comms; live-dot blips every
   ~10s.
2. Move a card between columns (via classic board or board-api `/action move`):
   within ≤10s the row flashes blue with a `⇄` badge on board2's corresponding
   tab, and tab counts update — no reload.
3. With ≥1 card in Doing, the Doing tab shows a repeating green ring pulse.
4. Comment on any card (`/apps/board-api/comment`); after the next cards.json
   regen the ticker picks it up.

## Notes

- Scope kept minimal per spec: ticker shows latest comms (which include the
  rescued/test-gate/held/deployed lines) rather than filtered event kinds.
- A card moved while the user is on another tab flashes when they switch over,
  since `movedIn` flags live until the next poll.
