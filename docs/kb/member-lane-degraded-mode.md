# Member-lane degraded mode — credit/quota outage notices

Card `kk-ha-degraded-mode-explain-capabilities-000d8b` (2026-11-24).
Learning case: KK's lane (ada-kk / kaewta persona) burned its
OpenRouter credit on 2026-10-14 — every reply transport failed and the
lane answered with **silence** (turn died as `response_interrupted`
with no words; voice connects died on a bare `provider_cap` error).
Future member lanes inherit the same contract — this is the pilot.

## The contract (`backend/degraded_mode.py` in ada-voice)

- `is_credit_failure(*errs)` — the sustained-outage classifier:
  billing caps, depleted credits/quota (daily/billing parks),
  unavailable/gone models, lane_budget holds. Transient rate limits
  (per-minute 429, explicit retry hints) and ordinary errors return
  False → the old interrupted/retry path stays, no false alarms. The
  quota taxonomy mirrors `gemini_pool._park_until` exactly.
- `turn_failure_notice()` — when EVERY text transport fails, the lane
  replies with a canned notice as a **normal assistant message** —
  transcript deltas + `response_completed`, so every client (LINE
  relay, TG relay, PWA chat, voice card log) already renders it.
- `connect_notice()` — billing-class provider-connect failures send a
  `{"type":"degraded","kind":"connect","message":...}` ws frame before
  the error+close; the voice card shows it and speaks it once in the
  machine voice (`avcSpeak`).

## What the notice says — "what still works"

- **Turn notice** (all text transports dead): credits ran out → can't
  think or use tools right now; this notice is the only reply still
  working; timers, cameras and smart-home routines keep running;
  ask `{contact}` to top up — back as soon as they land.
- **Connect notice** (voice held): voice paused → try the text lane
  (LINE/chat app) if it's alive; background jobs unaffected; ask
  `{contact}` to top up.

## Per-lane knobs (env, all optional)

| Env | Default | Meaning |
|---|---|---|
| `ADA_DEGRADED_LANG` | `auto` | `en`/`th`/`auto` — auto picks Thai when the triggering user text contains Thai script |
| `ADA_DEGRADED_CONTACT` | `Tony` | who to ask for a top-up |
| `ADA_DEGRADED_PARTICLE` | `ค่ะ` | Thai polite particle — the Thai template assumes a female-polite register; other registers should set `ADA_DEGRADED_NOTICE_TH` |
| `ADA_DEGRADED_NOTICE_EN` / `_TH` | built-in | full-template overrides (`{contact}` `{particle}` placeholders) |

## Where it landed (this dispatch — chaba side only)

- `integrations/ada-voice/backend/degraded_mode.degraded-mode.patch` —
  new module (classifier + bilingual templates)
- `integrations/ada-voice/backend/openrouter_provider.degraded-mode.patch` —
  `_complete()` emits the notice on total transport failure
- `integrations/ada-voice/pwa_server.degraded-mode.patch` — `degraded`
  frame on billing-class connect holds
- `stacks/{idc03/kk-ha,tony-dell/tony-ha,tony-dell/ada-ha}/www/ada-voice-card.js` —
  `degraded` / `live_budget_hold` / `notify_voice` cases (all three
  copies byte-identical, as before)
- `tests/ada/test_kk_degraded_mode.py` — 28 tests (classifier shapes,
  both languages, env knobs, patch tri-state, end-to-end `_complete`
  drive on a patched scratch tree)

Patches verified `git apply --check` against ada-voice `origin/main`
@ `fcb38ee` (2026-11-24).

## Deploy path (not done by this dispatch)

1. ada-voice: apply the three patches onto `origin/main`, merge,
   `deploy-ada.sh` on idc03 — **TONY GATE** (prod restart, deploy
   drains live sessions first).
2. kk-ha voice card ships with the next chaba stack deploy of the
   affected `www/` trees.
3. Per-lane envs may set `ADA_DEGRADED_CONTACT` / `ADA_DEGRADED_PARTICLE`
   to match each persona's register.

## Top-up pointers (unchanged — see `docs/kb/llm-credit-outage.md`)

- AI Studio prepay balance (`ai.studio/projects`) — billing gate, Tony.
- LiteLLM virtual-key budget raise — `ssot.llm-gateway.yml`.
- OpenRouter credit top-up for the `or-*` fallback legs.
- After recovery: note incident + duration in `ssot.llm-gateway.yml`,
  confirm fallback keys stayed armed in the lane env.
