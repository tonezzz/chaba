# Dispatch outcome — litellm-or-key-weekly-budget (SEC-1362)

Date: 2026-11-25 · Host: tony-dell · Card: `litellm-or-key-weekly-budget`

## What was done

Reviewed the live fleet OpenRouter key and **raised its weekly budget $1 → $5**.

- Key: OR name `idc02-openclaw`, label `sk-or-v1-74d…f6c`, hash
  `e7df92b7…`, live in `~/.config/secrets/mddb-gemini.env` on idc03
  (plus the other 3 rotate-or-key stores). Expires 2026-12-23.
- Before: `limit=1, limit_reset=weekly`, spent $0.5977, remaining
  $0.4023, reset 2026-11-30 — at the observed burn rate it would have
  capped around 11-26/27.
- After: `PATCH /api/v1/keys/{hash}` via `~/.config/secrets/or-management.txt`
  → `limit=5, limit_reset=weekly`, remaining $4.4023 (spend carries over).
  Verified on both `/api/v1/keys/{hash}` and the key's own `/api/v1/key`
  (~30s propagation).

## Evidence (why raise was warranted)

Account-wide OR `/api/v1/activity` reconciles with the key's $0.5977
weekly usage — essentially all account OR spend this window went through
this one key:

| driver | spend | source |
|---|---|---|
| google/gemini-embedding-2 (16,476 req) | $0.319 | gemini-ollama-proxy embed fallback during Gemini quota outage 11-23/24 (`OPENROUTER_PRIMARY=0` working as designed; 0 OR calls on 11-25 after recovery) |
| anthropic/claude-fable-5.1 (43 req) | $0.218 | LiteLLM `or-claude-fable-5.1`, mostly virtual keys `ada-sec1286`/`chaba` |
| deepseek/deepseek-v4-flash | $0.055 | LiteLLM |

LiteLLM_SpendLogs weekly OR totals are bursty: $23.76 (wk 11-02),
$26.87 (wk 10-19), $2.31 (wk 10-12), <$0.55 quiet weeks. $5/week bounds
exposure at ~$21.7/mo vs $66.80 remaining account credits; bench weeks
need a dedicated key — filed as **SEC-1384**
(`dedicated-openrouter-key-for-bench-eval-7ff299`).

## Alternatives rejected

- Keep $1/wk — predictable mid-week cap-out; the 11-12/13 incident
  (embed-legs-correlated-failure) already showed the cap defeating the
  redundancy design (OR 402/403 while Gemini was also down).
- Weekly rotation via rotate-or-key.sh — needs Tony to mint keys
  manually; doesn't fix sizing.
- Larger cap — bench spikes should not inflate the fleet emergency key.

## Files changed

- `docs/ssot/jobs/security/2026-11-25-or-fleet-key-weekly-budget-raise.yml` — decision record
- `docs/ssot/infrastructure/ssot.secrets.yml` — `openrouter-ada-safety` notes updated (current key identity + new budget; prior notes were a full rotation stale)
- Card comms posted via board-api; follow-up card SEC-1384 filed.

## How to verify

```
ssh idc03 'set -a; . ~/.config/secrets/mddb-gemini.env; set +a; \
  curl -s https://openrouter.ai/api/v1/key -H "Authorization: Bearer $OPENROUTER_API_KEY"'
# → data.limit=5, limit_reset=weekly, limit_remaining≈4.40, budgets[0].resets_at=2026-11-30
```

## Lessons

- or-management.txt is a provisioning-scope key: `PATCH /api/v1/keys/{hash}` works for limit/limit_reset changes — ssot.secrets.yml's "admin reads only" note was wrong.
- `/api/v1/key` (key's own view) lags provisioning writes ~30s — re-check before concluding a PATCH failed.
- OR `/api/v1/activity?date=YYYY-MM-DD` via the mgmt key gives per-model/day account spend — fastest way to attribute a key's usage when LiteLLM_SpendLogs only covers gateway traffic.
- gemini-ollama-proxy journal `via OpenRouter` lines are the tell for embed-fallback spend; count them per day before blaming LiteLLM.
