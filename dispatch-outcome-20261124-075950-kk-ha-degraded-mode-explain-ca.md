# Dispatch outcome — kk-ha degraded mode (explain capabilities when credits die)

Card: `kk-ha-degraded-mode-explain-capabilities-000d8b`
Branch: `dispatch/20261124-075950-kk-ha-degraded-mode-explain-ca` @ `22dee1fbee3`
Date: 2026-11-24, host tony-dell, repo chaba

## What was found

KK's 2026-10-14 OpenRouter depletion failure mode, traced in ada-voice
`origin/main` @ `fcb38ee`:

- **Text turns**: `OpenRouterTextProvider._complete()` — when the
  Gemini REST leg AND the OpenRouter leg both fail, the turn dies as
  `response_interrupted` with no words. Every LINE/TG/PWA text surface
  renders that as silence. This is the exact "answers credit
  exhaustion the worst way" behavior the card spec calls out.
- **Voice connects**: `pwa_server.voice_socket` sends a bare
  `{"type":"error","stage":"provider_connect","code":"provider_cap"}`
  then closes 1011 — no explanation of what still works.
- **Mid-session holds**: the reconnect loop already emits
  `live_budget_hold` frames, but `ada-voice-card.js` had no case for
  them (invisible to KK), and `notify_voice` frames were never spoken.

The card's `comms[0].spec` text is truncated at storage ("what still
works (") — the parenthetical is unrecoverable; the implemented
contract covers the stated requirement: a defined degraded-mode notice
on insufficient-credits/model-unavailable that explains what still
works.

## What changed (all committed on the dispatch branch)

**ada-voice staged drops** (`integrations/ada-voice/`, verified
`git apply --check` vs `origin/main` @ `fcb38ee`):

- `backend/degraded_mode.degraded-mode.patch` — NEW module:
  `is_credit_failure()` sustained-outage classifier (billing caps,
  depleted credits/quota, gone models, lane_budget holds; transient
  per-minute 429s and retry hints stay on the old path — quota
  taxonomy mirrors `gemini_pool._park_until`), plus bilingual EN/TH
  canned notices with `ADA_DEGRADED_LANG/CONTACT/PARTICLE/NOTICE_*`
  env knobs.
- `backend/openrouter_provider.degraded-mode.patch` — `_complete()`
  emits the notice as a normal assistant reply (transcript deltas +
  `response_completed`, ops event `degraded_mode_reply`) when every
  transport fails credit-shaped; reply emit extracted to `_emit_reply`,
  `_last_user_text()` feeds Thai auto-detection.
- `pwa_server.degraded-mode.patch` — billing-class connect failures
  send `{"type":"degraded","kind":"connect","message":...}` before
  the error+close.

**Voice card** — `stacks/{idc03/kk-ha,tony-dell/tony-ha,tony-dell/ada-ha}/www/ada-voice-card.js`
(all three byte-identical, as before): new `degraded` (show + speak
once), `live_budget_hold` (status line), `notify_voice` (speak) cases.

**Tests** — `tests/ada/test_kk_degraded_mode.py`: 28 tests —
classifier sustained/transient shapes, EN/TH notices + env knobs,
patch tri-state vs live checkout, and end-to-end `_complete` drive on
a patched scratch tree (402 → Thai notice deltas; per-minute 429 →
`response_interrupted` unchanged).

**Docs** — `docs/kb/member-lane-degraded-mode.md` (contract, capability
matrix, per-lane knobs, deploy path, top-up pointers),
`docs/ssot/jobs/ada/2026-11-24-kk-ha-degraded-mode.yml`, README drop #21.

## Result / verification

- `pytest tests/ada` — **339 passed, 1 skipped** (includes the 28 new).
- Pre-commit fast gate + SSOT validation passed on commit.
- Manual drive verified: credit failure → bilingual notice as normal
  reply; transient failure → unchanged interrupted path.
- NOT done (by design / gate): ada-voice merge to `main` + idc03
  `deploy-ada.sh` (prod restart — Tony gate); kk-ha card JS ships with
  the next chaba stack deploy.

## How to verify later

- `python3 -m pytest tests/ada/test_kk_degraded_mode.py -x -q`
- Apply the three patches to an ada-voice checkout and drive
  `OpenRouterTextProvider(tools=False)._complete` with `_or_turn`
  raising a 402 — expect notice deltas, not `response_interrupted`.

lessons:
- `~/CascadeProjects/ada-voice` HEAD was a feature branch
  (`ada-consult-pr12-edit`), not `main` — stage drop patches against
  `origin/main` (`git archive origin/main`), since deploy-ada.sh
  ff-merges main; `tests/ada/_checkout.materialize_head` follows
  whatever HEAD the checkout sits on.
- Hand-wiring `backend.*` submodules for tests is order-fragile —
  `realtime_provider` imports the whole backend package at module
  load; import the patched tree via `sys.path` + real package imports
  and evict stale `backend.*` from sys.modules first.
- A "quota exceeded" billing regex false-positives on transient
  retry-hinted 429s — quota-shaped errors must go through the
  daily/short/retry taxonomy before billing text matches.
- `git diff --no-index` labels carry literal paths — generate drop
  patches inside a scratch git repo for clean `a/`/`b/` headers.
