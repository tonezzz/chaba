# Dispatch outcome — board card photo/image attachments

**Card:** `board-attachments-photo-image-evidence-o-6fc9c2`
**Result:** implemented + end-to-end verified in this worktree on branch
`dispatch/20261117-085459-goal-implement-photo-and-image` (commit `2fa471c0a4`).

## What changed

- `scripts/board/board-api.py` — new `POST /attach` (alias `/upload`)
  `{id|card, filename, payload|b64|data, from?}`. Filename is basename'd +
  sanitized to `[A-Za-z0-9._-]` and extension-whitelisted (images, pdf,
  video, text/archive — nothing servable as an executable content-type, so
  uploads can't XSS the board origin). Payload is base64 (`data:` URI prefix
  stripped), capped at `BOARD_API_ATTACH_MAX_BYTES` (12 MiB decoded). The
  file lands at `docs/ssot/kanban/attachments/<card-id>/<name>` — inside
  the repo, committed in the same commit as the card (`save()`/`_commit_write`
  gained an `extra` paths arg) — and a comms entry links it:
  `attachment: <repo-path> — <orig> (N B)`. Name collisions suffix `-2`/`-3`;
  identical bytes reuse the file (idempotent re-posts).
- `scripts/render-board2.py` — mirrors the canonical attachment tree into
  `stacks/web/public/apps/board2/attachments/` every render (web container
  only mounts `/srv/public`, so the repo store isn't directly servable;
  Caddy's existing `handle_path /apps/board2/* { file_server }` then exposes
  `attachments/<id>/<file>`). `--if-changed` state hash gained a cheap
  names+size+mtime tree signature — no content hashing of multi-MB files.
  JS: `📎<n>` badge on card tiles, a "📎 Attachments" thumbnail strip in the
  card modal, and inline thumbs under any comms entry carrying a
  `docs/ssot/kanban/attachments/…` path. Images get `<img>` thumbs; other
  types get a 📎 download chip.
- `.gitignore` — ignores the generated `board2/attachments/` mirror plus
  `board2/archive.{html,json}` (pre-existing generated artifacts that were
  unignored).
- Docs — `docs/kb/board-api-write-door.md` endpoint table + note;
  `docs/ssot/kanban/ssot.kanban.yml` write_path endpoints;
  `docs/ssot/jobs/kanban/2026-11-17-board-card-attachments.yml` trail.
- `tests/board/test_board_api_mutations.py` — `AttachDoorTest`: validation,
  storage+comms link, sanitization/traversal, `data:` prefix, collision +
  idempotent re-post.

## Verification (all done live in this worktree)

- `BOARD_API_PORT=18787 python3 scripts/board/board-api.py`, then
  `curl -X POST /attach {id: attach-e2e-selftest, filename: "ups battery (1).png",
  payload: <b64 png>}` → `{"ok":true,"file":"docs/ssot/kanban/attachments/
  attach-e2e-selftest/ups-battery-1-.png"}`; file stored (valid PNG),
  card comms gained the link entry. Second upload with different bytes →
  `-2` suffix; same bytes → idempotent reuse; `.html` → 400. `/upload`
  alias verified.
- `python3 scripts/render-board2.py` → "1 attachments mirrored"; the file
  served `200 image/png` from `apps/board2/attachments/…` under a local
  http server; `cards.json` carried the comms entry; the extracted JS
  helpers produced the `<img>` thumbnail + gallery HTML under node.
- `pytest tests/board/` — 593 passed (27/27 in the mutations file,
  including the 5 new cases). `--selftest` has a pre-existing failure
  (unrelated `c3["action"]` assertion, fails identically on the base
  commit).
- Test artifacts (scratch card, attachment, mirror) removed after
  verification; no live card touched.

## Deploy notes

Goes live when the branch merges and `chaba-board-api.service` on idc03
restarts (it runs from the served checkout). No Caddy/route/unit changes
needed — the attachments mirror rides the existing `/apps/board2/*`
file_server and the web-srv-sync rsync to edge mirrors. Tony's two real
UPS photos can then be posted to `find-ups-replacement-batteries` via
`POST /attach`. Multipart isn't supported (JSON base64 only) — a board UI
upload button is a natural follow-up card.
