# dispatch-outcome — board-needs-you-strip

## What changed

`scripts/render-board.py` — the old "Needs you" strip (title buttons that only
opened the card modal) is replaced by a collapsible band above the columns,
`N things need you` in the header, expanded by default when N>0 (collapse
state persisted in `localStorage.board-ny-collapsed`). Items:

1. **Open requests** — every `requests[]` entry with `status != 'answered'`
   renders the card title, the ask text, and the answer controls INLINE:
   option buttons for `options:` requests, a free-text input + Answer button
   (Enter submits) otherwise. One click posts `/respond` — no modal.
2. **Stale review cards** — `column: review` and >24h since the last comms
   entry matching `-> review`/`→ review` (falls back to `updated`, then last
   comm timestamp), with no comms text matching
   `/verif|confirm|works|lgtm|tested|checks out/i`. Inline `✔ verify` button
   posts `/comment {from: tony, text: 'verified'}` which clears the item.
3. **Failed dispatches** — `action.status` in `failed|error`, with an inline
   `↺ Retry` button (`/action do=retry`) and the `action.result` snippet.

No new API surface — the band reuses `/respond`, `/comment`, `/action`.
Detection is page-side JS over the existing `cards.json` payload.

Supporting changes in the same file:
- `reqAnswerHtml(c, r)` extracted so the modal and the band share the answer
  controls; all `.rq-*` elements now carry `data-id` (card id) so they work
  outside the modal, with scope-aware lookups (band vs modal) so a request
  visible in both places can't cross-talk.
- Poll re-renders preserve in-progress typed answers + focus in the band.
- Regex escapes written as `\\d`/`\\s` in the f-string (same emitted JS,
  no Python 3.14 SyntaxWarning).
- `out_path.parent.mkdir` moved before the `cards.json` write — the renderer
  previously crashed in a fresh worktree where the gitignored output dir
  didn't exist.

`docs/ssot/kanban/ssot.kanban.yml` — `page_standard.needs_you_band` documents
the item rules and endpoints.

## Verification (done)

Ran the real `board-api.py` from this worktree on :8899 behind a tiny static+
proxy server (:8898), drove headless Chrome over CDP:

- Created a temp card (`zz-ny-band-test`, column=review, failed action,
  stale comms) and raised a request via `POST /request` with 3 options.
- Band showed "14 things need you" including all three item types; the test
  ask + red/blue/green buttons rendered inline.
- Clicked `blue` in the band → `/respond` wrote `answer: blue` on the card
  and the item disappeared on re-render.
- Clicked `✔ verify` → `verified` comm landed; the stale-review item cleared
  (one FAIL in the first pass was only a 3s wait being shorter than the
  write+render+load cycle — confirmed gone on re-check).
- Collapse toggle works and persists across re-renders.
- Test card deleted; `node --check` on the generated JS passes;
  `ssot-validate-all.mjs`: 1137 files, 0 errors.

## How to verify on the live board

After merge, the served checkout regenerates `index.html`/`cards.json`
(60s render timer or any board-api write). Open `/apps/board/` — the band
appears above the columns listing current open requests (mddb-rotated-files,
redispatch, tts-artifact-clean), the ~7 stale logs-* review cards, and any
failed dispatches. Answer a request by clicking an option button directly in
the band; it disappears after the ~1s write+render cycle.

## Git state

Uncommitted in this worktree (per dispatch rails): `scripts/render-board.py`,
`docs/ssot/kanban/ssot.kanban.yml`. No push, no deploy.
