# Dispatch outcome — dedicated-openrouter-key-for-bench-eval-7ff299

## What was decided and done

**Decision: option (a) — dedicated bench OR key + config split**, implemented
live on idc03 (the card's "Decide + implement" covered the litellm restart;
config backup at `~/.config/litellm/config.yaml.bak-20261125-orbench`).

Forensics first changed the design: LiteLLM_SpendLogs showed the burst weeks
were NOT fallback traffic. Every paid OR dollar in the last 7 weeks came via
direct `or-*` alias calls by dev-class virtual keys — chaba $20.17 fable
(wk 11-02), ada $13.14 fable + chaba $13.68 gemini-3.5-flash (wk 10-19).
Zero paid-OR spend ever flowed through job-class fallback chains, and
virtual-key allowlists already restrict paid or-* routes to dev/eval keys
(chaba can only reach or-deepseek/or-gemini-embedding-2/or-free-*; prod keys
michael/kk/mddb can't reach any paid or-* chat route).

Implementation:
1. Minted OR key `idc03-litellm-bench` (sk-or-v1-0e2…579) via
   `POST /api/v1/keys` using `~/.config/secrets/or-management.txt` —
   $30/week, expires 2026-12-25. Covers observed peak ($26.87/wk) +~11%.
   Stored as `OPENROUTER_BENCH_API_KEY` in idc03 `~/.config/secrets/litellm.env`
   (already mounted into the litellm container).
2. Repointed `api_key` on 7 paid or-* entries to
   `os.environ/OPENROUTER_BENCH_API_KEY` in BOTH live
   `~/.config/litellm/config.yaml` and repo `stacks/idc03/litellm/config.yaml`:
   or-gemini-2.5-flash, or-gemini-2.5-flash-lite, or-gemini-3.5-flash,
   or-gemini-3.5-flash-lite, or-claude-fable-5.1, or-gemini-3.1-pro-preview,
   or-deepseek-v4-flash.
3. Fleet `OPENROUTER_API_KEY` retained on: or-gemini-embedding-2 (embed
   resilience), or-gemini-3.1-flash-image (prod image fallback),
   consult-claude (repo-staged), vision + all or-free-* (:free, $0), and all
   non-LiteLLM consumers (gemini-ollama-proxy, openclaw sqlite,
   tony-dell/omen openrouter.env, ada-*.env).
4. Restarted `litellm.service` on idc03 — liveliness green.

## Verified

- `POST /api/v1/keys` + `GET /api/v1/key`: limit=30 weekly, remaining
  29.99964, expires 2026-12-25.
- e2e through gateway (master key): `or-claude-fable-5.1` OK — OR-side usage
  moved 0 → $0.00036 on the BENCH key while fleet stayed flat at $1.0413.
- `or-deepseek-v4-flash`, `or-gemini-3.5-flash-lite`, `or-free-nemotron-nano`,
  `gemini-3.5-flash-lite` all OK post-restart.
- YAML-validated all touched files; committed as `3c6799ad87` on the dispatch
  branch (not pushed — dispatcher merges).

## Deliverables

- `stacks/idc03/litellm/config.yaml` — 7-entry repoint + env comment
- `docs/ssot/infrastructure/ssot.secrets.yml` — `openrouter-litellm-bench`
  entry (slots, consumers, re-mint runbook)
- `docs/ssot/infrastructure/ssot.llm-gateway.yml` — providers.openrouter +
  openrouter_paid section updated
- `docs/ssot/jobs/infrastructure/2026-11-25-dedicated-or-key-bench-split.yml`
  — full decision record
- Live: idc03 `~/.config/litellm/config.yaml` + `litellm.env` + restarted
  litellm.service

## Residuals / follow-ups

- Bench OR key is not a key-watch probe slot and expires 2026-12-25 —
  re-mint steps documented in ssot.secrets.yml.
- If the bench key caps mid-eval-week, moved or-* routes 402; prod chains
  retain paid+free Gemini → colab → ollama legs (chain→OR spend observed
  is zero, so the fallback-leg role of or-gemini-3.5-* is theoretical).
- Pre-existing live↔repo config drift untouched (agent-local, consult-*,
  max_budget 75 vs 50).

lessons:
- LiteLLM_SpendLogs `model_group` = caller-requested alias, `model` = upstream
  served — group by both to separate direct or-* calls from chain fallbacks; here ALL paid-OR spend was direct alias calls, zero via fallbacks.
- OR provisioning API `POST /api/v1/keys` works with the or-management.txt key (same scope as the earlier PATCH) — no dashboard trip needed to mint fleet keys.
- LiteLLM per-entry `api_key: os.environ/X` is the only lever for splitting
  upstream credentials by route; caller-side (virtual-key) splitting isn't possible.
- Virtual-key model allowlists are a separate gate from the upstream OR key —
  chaba/bench keys 403 on or-claude-fable-5.1 even though the route works (master/unrestricted keys reach it).
- OR `/api/v1/key` usage lags ~1min — verify spend attribution after a short
  sleep, not immediately after the test call.
