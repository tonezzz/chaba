# dispatch outcome — tg_relay handle() forward provenance

**Card:** `tg-forward-provenance` · **Runner:** tony-macbook · **Date:** 2026-10-17

## What I found

The core of the requested feature was already implemented: ada-voice
`b205457` ("wip: mn-ha relay batch — gemini stt, forward provenance, …",
committed 2026-10-17 07:56 +07, now on `origin/main` @ `5ad03d2`, live on
idc03) added `_forward_label()` reading `forward_origin`
(sender_user/hidden_user/chat/channel + legacy `forward_*` fallbacks),
corpus filing under the original sender, `forwarded_by` manifest
provenance, and attribution prefixes on text/photo/voice turns.

So instead of re-implementing, I audited it against the card spec and
closed the residual gaps as a chaba-side drop patch (the repo-of-record
convention for ada-voice changes).

## What changed (all inside this worktree)

- `integrations/ada-voice/backend/tg_relay.forward-provenance.patch` —
  NEW drop patch vs ada-voice `main` @ `5ad03d2`:
  - `_forward_label` hidden-origin cases (`hidden_user`, legacy
    `forward_sender_name`) now suffix the label `— origin hidden`; when
    Telegram gives no `sender_user_name` the label falls back to the
    forwarder's identity via new `_forwarder_name()` (was bare
    "hidden user").
  - New `_media_desc()` + `_OTHER_MEDIA` + a `handle()` branch:
    forwarded `document/video/animation/sticker/contact/location/
    venue/poll/dice` (previously dropped silently by
    `if not text: return`) now reach the persona as described turns —
    `(forwarded from X) [received a document: name.pdf (200 KB) —
    content not viewable here] Their caption: …`. Non-forwarded media
    still drop (stray stickers shouldn't bill persona turns).
  - `_save_voice_clip`: forwarder now resolves through
    `TELEGRAM_USER_CALLERS` for both the fallback clip dir and manifest
    `forwarded_by` (a DM forwarder previously recorded as raw TG
    username, e.g. `tonezzz`, not `user-tony`).
- `tests/ada/test_tg_forward_provenance.py` — NEW: 16 tests via the
  `_drops` tri-state; drives the patched tg_relay standalone (label
  resolution for every origin type, forwarded text/document/sticker
  turn text, corpus filing under the original sender — the
  2026-10-16 incident replayed — and hidden-origin filing under the
  forwarder with the hidden flag in `forward_from`).
- `integrations/ada-voice/README.md` — Drop 14 entry with install +
  verified + residual notes.
- `docs/ssot/jobs/ada/2026-10-17-tg-forward-provenance.yml` — trail doc.

## Result / how to verify

- `/tmp/tgvenv/bin/python -m pytest tests/ada/test_tg_forward_provenance.py`
  → 16/16 green (bare uv venv: pytest, httpx, websockets; applies the
  patch to a scratch copy of `~/CascadeProjects/ada-voice` and drives it).
- `git apply --check` clean vs ada-voice `main` @ `5ad03d2`;
  `py_compile` clean.
- **Not deployed** — landing is `cd ~/CascadeProjects/ada-voice &&
  git apply <patch>` + `deploy-ada.sh` gates; live smoke is the first
  forwarded clip to @KrautMNBot.

## Judgement calls / follow-ups

- Hidden-user label keeps Telegram's claimed `sender_user_name` when
  present (it IS the origin's display name — hidden means no account
  link, not no name); forwarder fallback applies only when the name is
  absent. Documented in the drop README.
- Full TG document ingest (blob download + doc_read parity with LINE's
  file-doc-ingest drop) is out of scope — noted as a follow-up in the
  jobs doc; this drop guarantees a forwarded doc is acknowledged with
  provenance.
