# Dispatch outcome — tg-relay-turn-ok-unbound

Card: `tg-relay-turn-ok-unbound` (docs/ssot/kanban/cards/tg-relay-turn-ok-unbound.yml)
Date: 2026-11-24 · Host: idc02 · Branch: dispatch/20261124-165119-reproduced-on-origin-master-9e

## Result: already fixed — no code change needed

The `UnboundLocalError: turn_ok` in the forwarded-media-without-renderer
path of `tg_relay.forward-provenance.patch` was fixed the same day the
card was filed:

- Card captured via board-api: 2026-10-26 08:56 (repro on master 9e70ccc,
  08:23).
- Fix commit: `fda0685d77` "ada-voice drop 15: chat_send page=<slug>…"
  (2026-10-26 12:07) — its message calls out this exact bug: the
  forwarded-media branch "fell through to the shared `if turn_ok:` tail
  without initializing it". The diff adds `turn_ok = False` before the
  `try:` and `turn_ok = True` after `sess.send_turn(...)` in the staged
  patch, matching the photo branch's pattern.

The card sat in `backlog` for ~4 weeks after the fix landed; this
dispatch re-verified current state.

## Verification

- `git apply --check` on `integrations/ada-voice/backend/tg_relay.forward-provenance.patch`:
  applies **forward** cleanly against ada-voice `origin/main` @ `2e9a1ee`
  (drop still pending upstream) and against the idc02 checkout @ `6a39e3a`
  (46 behind origin/main — patch base is unaffected).
- Applied result audited: every `if turn_ok:` site in `handle()`
  (voice ~L1129, forwarded-media ~L1218, text ~L1270) is preceded by
  `turn_ok = False` in its own branch; `turn_ok = True` only after a
  successful send_turn/send_image_turn.
- `~/CascadeProjects/ada-voice/.venv/bin/python -m pytest tests/ada/test_tg_forward_provenance.py -q`
  → **16 passed** against a scratch `git archive origin/main` tree
  (ADA_PI=/tmp/ada-main) and also against the live idc02 checkout.
- Note: bare `pytest` (system python, no httpx/websockets) gives
  2 passed / 14 skipped via `importorskip` — use the ada-voice venv for
  a real run.

## Deliverables

- No repo changes (fix already on master).
- Card comms posted with the verification summary.

## How to verify

```
git archive origin/main | tar -x -C /tmp/ada-main   # from ~/CascadeProjects/ada-voice
git -C ~/CascadeProjects/ada-voice show origin/main:backend/tg_relay.py >/dev/null
ADA_PI=/tmp/ada-main ~/CascadeProjects/ada-voice/.venv/bin/python \
  -m pytest tests/ada/test_tg_forward_provenance.py -q   # 16 passed
```

lessons:
- Stale-card redispatch: before re-fixing, `git log -- <named files>` —
  this bug was fixed in fda0685d77 ~3h after the card was filed and the
  card just never moved.
- tests/ada/* need httpx+websockets: run them with
  ~/CascadeProjects/ada-voice/.venv/bin/python, not system pytest
  (which silently skips 14/16 via importorskip).
- The idc02 ada-voice checkout can lag origin/main by dozens of commits;
  verify patches against `git archive origin/main` in /tmp for a faithful
  base.
