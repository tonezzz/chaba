# Dispatch outcome — verify-live-max-budget-vs-ssot (2026-11-25)

Card: `litellm-proxy-wide-30d-budget-exhausted-04049d` (OPS-1349)

## What was found

- **Card premise partially stale.** Live `~/.config/litellm/config.yaml` on
  idc03 had already been raised `max_budget: 50 → 75` at 18:28 ICT and the
  litellm container restarted — before this dispatch ran. The proxy was
  already serving 200s again.
- **The 2026-11-07 "$75 raise" in ssot.llm-gateway.yml was SSOT-only.** Live
  config really did still say `$50` until today; repo
  `stacks/idc03/litellm/config.yaml` still said `$50`.
- **Proxy-wide budget is not a SpendLogs window sum.** LiteLLM tracks it as
  `LiteLLM_UserTable` row `user_id='litellm-proxy-budget'` — spend accumulates
  until `budget_reset_at` (2026-12-01 00:00 UTC), reset by the proxy
  ResetBudgetJob. Window spend crossed $50 at ~2026-11-24 23:00 ICT; journal
  shows `Budget has been exceeded! Current cost: 50.011…, Max budget: 50.0`
  (no `Key=` → proxy-wide) 422ing every route **at auth, before fallback
  chains** — even free/local legs died.
- **$75 was not enough.** Window spend was $62.01 with ~5.8 days left and
  recent burn ~$8/day → projected ~$110 → re-cap before Dec 1 reset likely.
- **Watcher gap:** `litellm-budget-watch.timer` (hourly, enabled earlier today
  by card `litellm-budget-watch-enable`) only judged per-key
  `LiteLLM_VerificationToken` rows — today's incident was the proxy-wide row,
  which nothing watched.

## What changed

- **Live idc03** `~/.config/litellm/config.yaml`: `max_budget 75 → 120`
  (backup `config.yaml.bak-budget-20261125`), `systemctl --user restart
  litellm.service`. Post-restart: `LiteLLM_UserTable` shows max_budget=120,
  spend=62.01 carried, reset 2026-12-01; real `/v1/chat/completions` call via
  LITELLM_KEY_CHABA returned 200.
- **Repo** `stacks/idc03/litellm/config.yaml`: `max_budget 50 → 120`.
- **SSOT** `docs/ssot/infrastructure/ssot.llm-gateway.yml` `budgets.proxy_cap`
  rewritten with the real history ($50→$75→$120, why $120, watcher note).
- **`scripts/litellm/budget-watch.py`**: appends the `litellm-proxy-budget`
  row as a synthetic `proxy-wide` finding (psql source; `/key/list` API
  fallback can't see it). Verified live on idc03 via `/tmp` copy: reports
  `proxy-wide: $62.05/$120 (52%) ok`.
- **`scripts/litellm/daily-ledger.py`**: budget table now UNIONs the proxy
  row; published "Proxy ceiling" footer is live-read instead of hardcoded
  `$50/30d`.
- **Job trail**: `docs/ssot/jobs/infrastructure/2026-11-25-litellm-proxy-budget-cap-raise.yml`.
- Committed on `dispatch/20261125-190752-verify-live-max-budget-vs-ssot`
  (`51ad92f83a8`), incl. refreshed `reports/SSOT_OPTIMIZATION_WARNINGS.json`
  baseline (full run — ssot.llm-gateway.yml bloat warning is new vs baseline).

## Decision: raise (to $120), not wait-for-reset

Reset is 2026-12-01 (~5.7 days out). At recent burn the window projects to
~$105–115 — $75 would likely have re-capped mid-window and re-broken every
route. $120 covers the projection, stays below the ~$150 sum of capped
per-key budgets (proxy remains the outer brake), and is the only bound on
uncapped `LITELLM_KEY_BENCH`. Re-check after the Dec 1 reset against
December's real run-rate.

## How to verify

- `ssh idc03 'podman exec litellm-db psql -U litellm -d litellm -c "SELECT
  max_budget, spend, budget_reset_at FROM \"LiteLLM_UserTable\" WHERE
  user_id='"'"'litellm-proxy-budget'"'"'"'` → 120 / ~62 / 2026-12-01.
- `ssh idc03 'journalctl --user -u litellm.service --since "-10min"'` → 200s,
  no proxy-wide BudgetExceeded.
- budget-watch proxy coverage goes live on idc03's exec checkout after this
  branch merges + `chaba-repo-sync.timer` runs (≤1h); the hourly timer then
  judges `proxy-wide` too.

## Notes / leftovers

- Live `~/.config/litellm/config.yaml` still drifts from repo beyond the cap
  (`agent-local` route live-only; `consult-*` routes repo-only) — pre-existing,
  already flagged in `live_audit`; not reconciled here.
- Per-key caps unchanged: `chaba` $31.06/$40 (78%), `ada-dev-2` $10.004/$10 at
  cap (still 422ing — watcher already filed `budget-watch-ada-dev-2`).
- `reports/2026-11-18-consultant-reroute-verify.md` mentions the old $75 proxy
  cap — point-in-time report, intentionally not rewritten.

lessons:
- LiteLLM proxy-wide `litellm_settings.max_budget` is NOT a SpendLogs window
  sum — it's the `LiteLLM_UserTable` row `user_id='litellm-proxy-budget'`,
  spend accumulating until `budget_reset_at` (ResetBudgetJob). Budget math
  must read that row, not `sum(SpendLogs)`.
- A proxy-wide budget 422 fires in `user_api_key_auth` BEFORE routing — every
  model including free/local fallback legs dies; the error has no `Key=`
  field (per-key errors do).
- SSOT "raised" claims can be SSOT-only: always verify the mounted live config,
  not just the repo copy or the SSOT text.
- litellm-budget-watch.timer watches per-key budgets only; the proxy-wide row
  needs the `LiteLLM_UserTable` query added (done in this dispatch — lands on
  idc03 after merge + repo-sync).
