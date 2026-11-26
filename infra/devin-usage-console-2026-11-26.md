# Devin usage meter — Console capture 2026-11-26

Source: operator read of `https://app.devin.ai/settings/usage` (Pro plan).
The allowance-remaining percentage is NOT machine-readable on Pro — the
consumption API is Enterprise-only and `devin` has no usage subcommand
(see `devin-usage-allowance-visibility` card / DEV-1332). These numbers were
read visually and relayed into the devin-handoff session notes and the
`bigquery-usage-ledger-writer` card spec.

## Readings

| When (UTC) | Used | Context |
|---|---|---|
| ~12:47 | 4% | before DEV-1209 handoff launch (`--remaining-pct 96` gate, see `devin-cloud-baseline-measure.md`) |
| ~15:19–15:28 | 12% | at `bigquery-usage-ledger-writer` card capture (board-api, 22:19 +07) |

Delta over the window: **+8 quota points** for **2 verified PRs**
(chaba PR #240 from ADA-0062 `d8e3e0fc…`, chaba PR #241 from DEV-1209
`6c6a00dd…`) → **4.0 quota-points per PR**.

Both cloud sessions reported `acus_consumed=0.0` and
`on_demand_usage=null` in the v3 polls embedded in
`devin-daily-usage-2026-11-26.json` — the quota delta above is the only
cost signal that moved.

Local dispatch burn that day ran on SWE-2 Flash High, which is free for
self-serve Desktop/CLI until 2026-12-04 18:00 UTC — it legitimately
consumed no cloud quota.
