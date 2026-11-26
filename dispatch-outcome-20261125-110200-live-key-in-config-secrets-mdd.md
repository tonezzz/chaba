# Dispatch outcome — litellm-or-key-weekly-budget (SEC-1362), attempt 2

Date: 2026-11-25 · Host: tony-dell · Card: `litellm-or-key-weekly-budget`

## What this attempt was

Attempt 2 was a **zombie-claim restart** (OPS-1071): attempt 1
(`devin-task-20261125-103517-…`) finished cleanly at 10:57 — exit=0, work
committed as `59a6d0984a1`, branch auto-merged to origin/master, card moved
to `review` with `action.status: done` / `verified: true`. The runner's
checkpoint commit failed on 1 uncommitted file and the claim response was
lost, so the dispatcher re-claimed the card at 11:02. No rework was needed.

## Verified state (re-checked live this session)

- `GET /api/v1/key` on idc03 with the live `OPENROUTER_API_KEY` from
  `~/.config/secrets/mddb-gemini.env` returns:
  `limit=5, limit_reset=weekly, limit_remaining=4.4023,
  spend_usd=0.5977 (carried), resets_at=2026-11-30T00:00Z` — the attempt-1
  `PATCH /api/v1/keys/{hash}` ($1→$5) persisted.
- On master (`59a6d0984a1`):
  - `docs/ssot/jobs/security/2026-11-25-or-fleet-key-weekly-budget-raise.yml` — decision record (spend analysis, rationale, rejected alternatives)
  - `docs/ssot/infrastructure/ssot.secrets.yml` — `openrouter-ada-safety` notes corrected (or-management.txt is provisioning-scope; "admin reads only" note was stale)
  - `dispatch-outcome-20261125-103517-live-key-in-config-secrets-mdd.md` — attempt-1 outcome doc
- Follow-up card **SEC-1384** (`dedicated-openrouter-key-for-bench-eval-7ff299`)
  filed for the bursty bench/eval weeks ($20–27 historically) that no sane
  fleet weekly cap can carry.
- Card comms confirm DONE: budget reviewed **and adjusted** ($1→$5/wk),
  justified in the decision record — bounds exposure ~$21.7/mo vs $66.80
  remaining account credits; key expires 2026-12-23; key-watch +
  litellm-budget-watch still alert before exhaustion.

## Files changed (this attempt)

- `dispatch-outcome-20261125-110200-live-key-in-config-secrets-mdd.md` — this doc
- Card comms posted via board-api (verification note).

## How to verify

```
ssh idc03 'set -a; . ~/.config/secrets/mddb-gemini.env; set +a; \
  curl -s https://openrouter.ai/api/v1/key -H "Authorization: Bearer $OPENROUTER_API_KEY"'
# → data.limit=5, limit_reset=weekly, limit_remaining≈4.40, resets 2026-11-30
```

## Lessons

- Zombie-claim restarts (OPS-1071) can fire even when the prior run merged cleanly — always check card comms + `git log origin/master` for the work commit before redoing anything.
- The runner's checkpoint `git commit` can fail on a single dirty file while the session's own commits still merge fine — verify via `git ls-files`/`git log` on master, not the checkpoint message.
