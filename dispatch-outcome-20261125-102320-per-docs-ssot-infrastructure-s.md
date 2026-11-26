# Dispatch outcome — kk-mac-offload-flash-lite (2026-11-25)

## What was done

Produced the routing proposal the card asked for:
`docs/ssot/jobs/infrastructure/2026-11-25-kk-mac-flash-lite-offload.yml`
(YAML-validated). Raised board request `routing-proposal-written-docs-ssot-jobs-edd01d`
on the card with approve options (a) staged P1+P2 / (b) P1 only /
(c) immediate repoint / (d) adjust.

## Key finding (corrects the card's premise)

The spec assumed tool-call/summary/classify job-class lanes drive the
steady flash-lite spend. LiteLLM_SpendLogs (queried live on idc03
litellm-db) says otherwise:

- summary/classify/bench have been kk-mac leg-1 since 2026-11-13 —
  November paid-leg spill is ~$0.09 total. tool-call/voice-aux ~zero
  volume (6 and 1 calls).
- ~85% of November flash-lite spend (~$21 of ~$24.6) is **opencode
  callers on the real-name `gemini-3.5-flash-lite` chain** (chaba +
  ada-sec1286 keys) — interactive CLI/openchamber plus free_lane
  dispatches (`LANE_MODELS["free_lane"] = litellm/gemini-3.5-flash-lite`).
- chat-local: 8501 calls, $0.00 — the free-lane pattern already works.

## Proposal contents

- P1: insert `ollama-llama32-3b-kkmac` at tool-call leg-3 (resilience
  position; llama3.2:3b is the only T3-qualifying local model after the
  11-25 rerun — qwen2.5:32b regressed below acc+deference bars).
- P2 (the real lever): new `agent-local` job-class alias, free-local-
  first chain [qwen32b-kkmac@shim → qwen7b@tonydell → llama3.2@idc03 →
  colab → paid lite last], repoint free_lane only after an
  evals/opencode-lane gate passes.
- P3 optional caller repoints (~$1.7/mo batch jobs), P4 eval queue for
  new kk-mac pulls qwen3:30b-a3b / gpt-oss:20b.
- Live-verified today: kk-mac awake, admission shim eligible, and
  qwen2.5:32b returns correct OpenAI tool_calls frames via :11447.

## How to verify

- Doc: `docs/ssot/jobs/infrastructure/2026-11-25-kk-mac-flash-lite-offload.yml`
- Spend SQL is embedded in the doc's `evidence.spend_attribution`;
  rerun the model_group query on litellm-db to reproduce.
- Deploy is gated on the board request answer — nothing was changed
  live (no config edits, no restarts, per dispatch rules).

lessons:
- LiteLLM_SpendLogs `model_group` = the alias the caller sent; grouping
  flash-lite spend by it (plus request_tags UA) reveals the real spend
  driver — job-class aliases can look busy while the real-name chain
  burns the money. Always attribute before proposing route moves.
- The 2026-11-25 eval-rerun artifacts (commit 893107b1c4) live on
  `origin/dispatch/20261125-074813-...`, NOT yet on master despite the
  card comms claiming a merge — `git merge-base --is-ancestor` before
  trusting "merged" claims.
- All four `ollama-*-kkmac` deployments share api_base :11447 — when
  the shim denies, every kk-mac leg fails together; a second kk-mac
  model in the same chain adds nothing during sleep windows.
- kk-mac was awake and fast today (shim stats admitted 271/denied 15/
  proxied 3780); member-device lanes are bursty — probe :11447/health
  before assuming gates fail.
