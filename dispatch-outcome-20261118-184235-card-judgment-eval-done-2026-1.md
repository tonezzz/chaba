# Dispatch outcome — kk-mac routing proposal (re-land)

Card: `kk-mac-routing-proposal-fold-local-qwen2-4d513b` (OPS-0095, parent
eval `kk-mac-card-judgment-eval` / KNB-1087). Runner: tony-omen.

## What I found

This card was already worked once: dispatch `20261113-202232` wrote the
routing proposal, got Tony's approval on option (a), and DEPLOYED the
gateway legs live on 2026-11-13 ~20:45 ICT. But its branch conflicted
with master 15 times and merge-sweep never landed it — so on master the
doc and two supporting code changes were missing, while the deployed
config had already been synced in separately.

State on master at dispatch time:
- `ssot.llm-gateway.yml` + `stacks/idc03/litellm/config.yaml`: kk-mac
  legs already live — `summary`/`classify`/`bench` leg-1 =
  `qwen2.5:32b` via admission shim `:11447`; `chat-local` leg-2 = kk-mac
  behind tony-dell qwen7b; `tool-call` untouched; voice-aux/chat/
  vision/image/embedding excluded. All as proposed.
- `kkmac-admission-shim.service` (60C temp/load/staleness gate) already
  deployed — the member-device risk from v1 is mitigated.
- Missing: the proposal doc itself, the `lane-savings.py`
  `action.executor` attribution patch, and the `qwen3:8b -> qwen2.5:32b`
  executor pin.

## What changed (commit 2035c58960 on dispatch/20261118-184235-*)

- `docs/ssot/jobs/devnest/2026-11-18-kk-mac-routing-proposal.yml` — v2
  proposal doc: job_class placement table (live vs deferred), savings
  evidence path, risks, T3 rerun cadence.
- `scripts/board/lane-savings.py` — `EXECUTOR_LANES` map: `kk_mac_local`,
  `jules`, `nlm_batch`, `opencode` now attribute to cheap lanes before
  the type fallback. Verified: Nov-2026 report now shows kk_mac_local
  (3 cards), jules (13), nlm_batch (1) instead of folding into 'devin'.
- `qwen3:8b -> qwen2.5:32b` repin across the whole kk_mac_local lane:
  `kk_mac_executor.py` (DEFAULT_MODEL), `kk_mac_llm.py` (2 defaults),
  `kk_mac_lane_worker.py`, `kk_mac_plan_validator.py`,
  `devnest_report_feed.py` — the eval showed qwen3:8b parse-fragile
  (0.674 acc, 16 parse-fails vs 0.857/0 for qwen2.5:32b).
- `ssot.devnest-lanes.yml` — expected_tokens note updated to match.

## Routing proposal summary (what the doc says)

- LIVE leg-1 (kk-mac qwen2.5:32b via shim): `summary`, `classify`, `bench`
- LIVE leg-2: `chat-local` (tony-dell qwen7b stays leg-1)
- DEFERRED: `tool-call` — candidate leg-3 only after 3 consecutive
  qualifying runs AND deference >= 0.90 (currently 0.878)
- Excluded: `voice-aux`, `chat`, `vision`, `image`, `embedding`
- Savings: ~$22/window movable REST spend; evidence via lane-savings.py
  (counts) + LiteLLM ledger delta (dollars); token-evidence gap noted.
- Rerun cadence: `kkmac_eval.sh qwen2.5:32b` each kk-mac online window,
  >=24h apart, 3 runs in ~2 weeks; streak resets on corpus/model/prompt
  change; try defer-biased prompt variant to probe the 0.878 gap.

## Verification

- `pytest tests/devnest/test_kk_mac_{llm,executor,lane_worker,admission}.py`
  — 54 passed
- `python3 scripts/board/lane-savings.py --month 2026-11` — new lanes
  visible in report
- SSOT validation + prose-smell clean; commit gate passed (15s test
  budget advisory only)

## Not done / for follow-up

- Branch NOT pushed (dispatch rule); merge-sweep can land it after the
  session-end checkpoint/push, or a human merges commit 2035c58960.
- tool-call leg-3 remains gated on 3 qualifying eval runs.
- Token evidence for kk_mac_local still unevidenced — needs
  finish_kk_mac_lane to copy usage into action.result (carded as
  next-step in the doc).
