# board-structured-responses — ask.options one-click answers

## What changed

- **`scripts/board/board-api.py`** — `POST /respond` without `request_id`
  now answers the card-level `ask:` (`{id|card, option: N}` picks
  `ask.options[N]`; `{id, text|answer}` is free text resolving to a
  unique option match — exact id/label or unique label prefix, else
  verbatim). Writes `ask.status/answer/answered_at`, comms
  `answered ask: <label>`, and the same `awaiting_action` triage nudge
  as requests. Resolved label feeds `answers.jsonl` (request_id `ask`)
  for running sessions. `card` accepted as an `id` alias; `text` as an
  `answer` alias. Selftest extended (option bounds, reopen, option
  resolution, string-ask normalization, body mutation for delivery).
- **`scripts/render-board.py`** — open `ask` renders as a needs-you
  item (question + button per option + Other input) and a `Decision`
  section in the card modal; answered shows `❓ q → answer`. Card badge
  `needs you ×N` counts the ask. `.ask-opt` posts `{id, option}`;
  `.ask-btn`/`.ask-in` post `{id, text}`; Other text survives the poll
  re-render in both scopes.
- **`scripts/board/kanban-stats.py`** — open card-level ask counts as
  one `open_requests` item (`request: "ask"`).
- **`docs/ssot/kanban/ssot.kanban.yml`** — `ask:` schema documented;
  `/respond` signature updated.
- **Migration** — `service-onboarding-standard` (the only other
  `review_kind: decide` card lacking an ask) now carries
  `ask.options`. `edge-ha-restructure` already had it — it's the live
  prototype Tony will see first.
- **`ssot.ada-participation.yml`** — T2 gap extended: ada_board_write
  requires `request_id` client-side, so the voice answer path needs a
  one-spot ada-pi patch (make it optional + surface `ask` in
  `_compact_card`). The API side already accepts `{id, text|option}`
  and resolves `yes` → the Yes option.

## Verify (all run in this worktree)

- `board-api.py --selftest` → ok
- e2e, in-process server + temp CARD_DIR, loopback identity:
  `{card, option: 0}` on edge-ha-restructure → 200, `ask.status=answered`,
  comms `answered ask: Yes — full B+C`, `awaiting_action` set (=
  decision recorded, card flagged for triage); re-answer → 400;
  `{text: "yes"}` → resolves to `Yes — expand`; forged
  Tailscale-User-Login + LAN XFF → 403; loopback → 200; running card →
  `answers.jsonl` gets the resolved label.
- `render-board.py` → renders; generated JS `node --check` clean.
- `ssot-validate-all.mjs` → 1626/1626 valid, 0 warnings.

## Not done (by design)

- No deploy — board-api.service + rendered board update on merge to
  master on the served checkout (chaba-tony-dell); promotion needs
  explicit approval.
- Did NOT answer Tony's edge-ha-restructure decision — verification
  used a copied card in a temp dir; his real ask stays open.

Job trail: `docs/ssot/jobs/kanban/2026-10-07-board-structured-responses.yml`
