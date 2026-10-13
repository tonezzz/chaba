# Dispatch outcome — live-session-token-diet (OPS-0509), attempt 2

## What changed (live)

`~/.config/secrets/ada-ha-tony.env` on idc03 gained, right after `ADA_TOOL_CALL_BUDGET=10`:

```
ADA_CONTEXT_TRIGGER_TOKENS=47000
ADA_CONTEXT_TARGET_TOKENS=35000
```

`ada-ha-tony.service` restarted; `/proc/<MainPID>/environ` confirms both vars live. Backup at `ada-ha-tony.env.bak-20261013`.

## Why

The lane ran code defaults 32000/24000 against a measured ~27.8k static floor
(49-decl keep-list, OPS-0583) — trigger ~1.15x floor where
`ssot.tokens.policy.yml` wants >= ~1.7x, and target sat BELOW floor so every
compression was a max-trim fired almost every turn. 47k/35k restores
1.69x/1.26x.

## Key finding (documented in job doc)

A compliant trigger (>=47.3k) necessarily exceeds the `ADA_CONTEXT_TURN_BUDGET`
rotation ceiling (45k) at floors >= ~26.5k — so compression effectively never
fires on ada-ha-tony now; the window is rotation-bounded (sawtooth ~28k->45k,
clean reconnect, ConversationMemory carries continuity). That removes the
unmoor->tool-storm path entirely — the mechanism behind the 134M/day burn
(234x set_facial_expression storms). The alternative (raise turn budget to
~55k so compression fires at 47k->35k) preserves more continuity but sits
closer to the ~78k degradation point and holds a higher mean context — noted
as an option in the job doc, not taken.

## Verification

- `systemctl --user is-active ada-ha-tony` → active; process env confirms vars.
- 1-turn scenario-live smoke on ws://127.0.0.1:8002/ws → PASS, first turn
  in=18139 (text channel; under trigger, no regression).
- `notebooklm-rest-api.env` (loads second in the unit) carries no
  `ADA_CONTEXT_*` — no silent override.
- `node scripts/ssot-validate-all.mjs` → 2269/2269 valid, 0 errors.

## Repo changes (dispatch branch commit 10ad26143)

- `docs/ssot/jobs/ada/2026-10-13-live-session-token-diet.yml` — full job doc
  (burn profile, rotation interplay, remaining levers).
- `docs/ssot/ssot.tokens.policy.yml` — per-lane floors + the
  trigger-vs-rotation collision note.
- `docs/ssot/apps/ssot.apps.ada_ha.yml` — env surface gains the
  Context-window/budget vars (previously undocumented).
- `docs/ssot/jobs/ada/2026-10-13-line-voice-enroll-recognize.yml` — unbroke 3
  plain scalars (`{full: true}` / `Card rails:` colons) failing the validator;
  likely what failed attempt 1's verify.

## Follow-ups filed

- ADA-0601 `expression-call-batching` — cosmetic calls re-bill full context.
- ADA-0602 `michael-lane-context-window` — same fix pending (~49k/37k).
- `session-turn-age-caps` lever noted in job doc only (vaguer, needs design).

## Watch next

usage.jsonl in/turn distribution over the next 24-48h — expect the 25-35k
churn band (424 turns/24h) to spread up toward 45k with rotation events
(`context_rotate` ops events) instead of compression. Burn/day should drop
if storm-mode turns were the driver; if not, the floor itself is next
(ADA-0586 lazy schemas).

lessons:
- ssot-validate-all gate can already be red on master from a previous merge — check baseline errors before assuming your edits broke it.
- ada-ha-*.env is NOT bash-sourceable (unquoted parens in ADA_IDENTITY_INSTRUCTIONS) — extract single vars with grep/cut instead of `source`.
- notebooklm-rest-api.env loads SECOND in ada-ha units — any var set there silently overrides ada-ha-*.env.
- `{full: true}` and `Word: rest` inside YAML plain scalars = "mapping values are not allowed here"; `{full:true}` (no space) is safe mid-scalar.
- ADA_CONTEXT_TURN_BUDGET (rotation) preempts sliding-window compression whenever trigger > 45k — the two knobs are ordered, not independent.
