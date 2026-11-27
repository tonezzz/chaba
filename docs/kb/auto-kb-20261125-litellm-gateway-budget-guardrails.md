---
category: infrastructure
status: verified
created: 2026-11-25
source: auto-kb
title: "LiteLLM Gateway Budget Guardrails"
tags: [litellm, gateway, budget, ops, infrastructure]
---

# LiteLLM Gateway Budget Guardrails

Verified operational procedure for monitoring and raising the proxy-wide spend cap on the LiteLLM gateway (idc03).

## Root Cause

LiteLLM proxy returned HTTP 422 `Budget exceeded` when `current_cost` ($50.01) exceeded `max_budget` ($50.0) on virtual key `LITELLM_KEY_CHABA`.

## Resolution

1. **Read current spend**: `curl -H "Authorization: Bearer $LITELLM_KEY_CHABA" http://100.102.134.91:4000/key/info` → returns `current_cost`, `max_budget`, `spend_logs`
2. **Raise proxy-wide cap**: Edit `/home/tony/.config/litellm/config.yaml` on idc03, set `max_budget: 75` (was 50)
3. **Restart gateway**: `systemctl restart litellm.service`
4. **Verify**: Repeat `/key/info` call; confirm `max_budget: 75` and `current_cost` < new cap
5. **Sync SSOT**: Update `docs/ssot/infrastructure/ssot.llm-gateway.yml` `budget.max_budget_usd` to 75

## Files Touched

- `/home/tony/.config/litellm/config.yaml` (live config on idc03)
- `docs/ssot/infrastructure/ssot.llm-gateway.yml` (SSOT doc)
- `systemd` unit: `litellm.service`

## Operational Notes

- The proxy-wide `max_budget` applies to **all** virtual keys; per-key budgets are separate (not used here).
- Spend ledger at `~/.config/litellm/spend_logs.json` tracks per-call costs; `/key/info` aggregates.
- Automated timer (OPS-1361) rotates ledger entries; budget watch card (OPS-1360) alerts at 80% utilization.
- `LITELLM_KEY_CHABA` model allowlist unchanged during this change.

## Related

- OPS-1360 (budget watch card), OPS-1361 (ledger timer), OPS-1363 (kk-mac offload)
- `scripts/sync-kb-to-mddb.py` for KB indexing