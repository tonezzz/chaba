# Dispatch outcome — live-voice-burn-context-replay (ADA-0631, attempt 2)

## Verdict on the card's findings

Re-measured against live `usage.jsonl` + journald on idc03 (per-day
in-tokens):

| day | turns | in-tokens | note |
|---|---|---|---|
| 10-12 | 4084 | 128.8M | original whale day (5.5M of it t-ctx test rows) |
| 10-13 | 1095 | 27.7M | diet levers landing |
| 10-14 | 2966 | 63.8M | the card's dig day — mostly ada-dev Live sessions |
| 10-15 | 20 | 0.39M | collapsed |
| 10-16 | 37 | 0.91M | all lane=tony, real voice sessions |

The 85%-text-replay / ada-dev-63% burn is already solved in substance:
scenario transport moved 40/41 smoke scenarios to `mode=text` (ada-voice
f485a27 — REST via LiteLLM, no upstream Live session), LINE moved to the
gateway chat alias, and the rotation/tool-cap/keep-list/lazy-schema stack
cut the per-turn floor. Residual Live burn is ~<1M in/day. TEST-POLLUTION
is also fixed: ada-voice `tests/conftest.py` sets `ADA_USAGE_LOG=off`;
zero non-10-hex session rows in the ledger since 10-15, and both chaba
readers (spend-ledger.py, usage-feed.py) already filter them on read.

## Live defect found + fixed

While the burn died, a regression appeared: `scenario-provider-gate.py`
flapped `ada-scenario-smoke` between ok/quota-dead every other hour
since ~10-15. Cause: text-mode sessions on ada-dev produce **none** of
the gate's healthy markers (`usage turn`/`ready event`/... = 0 in 24h vs
2197 chat/completions calls), so every LiteLLM `bench`-key
budget_exceeded 422 in the 70-min window read as provider-dead — even
though the OpenRouter fallback answers 200 for every turn.

Fix in `scripts/ada/scenario-provider-gate.py`:
- `RX_QUOTA` split into `RX_QUOTA_LIVE` (1011 / 'exceeded your current
  quota' / resource-exhausted) and `RX_QUOTA_REST` (budget_exceeded /
  429s); new `RX_OK_REST` counts served completions (httpx `POST
  ..(chat/completions|generateContent).. HTTP/x 200`).
- `check_quota` now requires same-transport refutation: live dunning is
  cleared only by live markers (a REST 200 cannot mask a dead Live
  upstream on an authorized prod run); REST dunning is cleared by any
  served completion; connect-fail streaks still need upstream markers.
- detail dict gains `live_quota_lines` + `rest_served`.

## Verification

- Synthetic-journal matrix: 10/10 cases, incl. masked-death guard
  (live dunning + only REST 200s → still quota-dead) and conn-fail
  streak + REST 200 → quota-dead.
- Live dry-run on idc03 vs ada-dev: `ok — quota_lines=46
  live_quota_lines=0 rest_served=63` (stock script returned quota-dead
  at the 11:00 run).
- NOT deployed — the ExecCondition resolves
  `%h/CascadeProjects/chaba/scripts/...` on idc03; propagates on merge +
  chaba-repo-sync (hourly). Next flapped hour after merge should log
  `ok` instead of skip.

## Open items (flagged on the card)

- LiteLLM `bench` virtual key: $2/30d cap exhausted (Current
  2.008/Max 2.0) — every ada-dev text turn pays a 422 round-trip before
  OpenRouter. Raise cap / mint fresh dev key / accept the latency —
  spend decision, not changed here.
- ada-voice-scope levers (outside this repo): skip the gateway attempt
  when the key is known-capped; Live session resumption for the ~16K
  reconnect re-prime — already covered by ada-voice-session-churn.

## Files

- `scripts/ada/scenario-provider-gate.py` — transport-scoped quota
  refutation.
- `docs/ssot/jobs/ada/2026-10-16-context-replay-verdict.yml` — full
  evidence trail.

Commit `f92b11c9e` on `dispatch/20261016-111232-live-voice-burn-context-replay` (not pushed).

lessons:
- scenario-provider-gate judges health per transport — text-mode units
  log zero 'usage turn'/'ready event' markers; only completion 200s prove
  a text lane alive. Check `live_quota_lines` vs `rest_served` in the
  gate detail before trusting a quota-dead verdict.
- The fleet ledger lives at ~/CascadeProjects/ada-voice/data/usage.jsonl
  ON idc03 (shared by all ada-* units); tony-dell's copy is a 183-line
  stub — always ssh idc03 for burn numbers.
- 'lane'/'unit' fields only started populating ~10-16; older rows need
  journald session_id attribution.
- LiteLLM virtual keys carry max_budget caps that surface as 422
  budget_exceeded in backend journals — a capped key produces perpetual
  "quota" noise while fallbacks keep serving.
