# Dispatch outcome — pin-a-free-openrouter-model-for-store-aw-ed0cc2

## What changed

`scripts/bench-edu-manage.py` — the store-awareness A/B pipeline
(`--lanes clawbot`, baseline vs `--agent-topics` treatment on the
13-task MockStore fixture):

- New `OR_PINNED_MODEL = "nvidia/nemotron-3.5-super-vl:free"`; the
  `--or-model` default changed from `openrouter/free` (dynamic router —
  rotated 8–12 model IDs per rep in the 2026-10-24 run and can land on
  non-chat legs) to the pinned `:free` slug. `openrouter/free` remains
  available via explicit `--or-model openrouter/free`.
- Model choice: or-free scorecard 2026-10-23 composite 100.0 / p50 1.9s
  (best of 17 live `:free` models) and the exact model of this card's
  completed 3-rep baseline, so the pending store-aware treatment stays
  comparable. OR `:free` daily cap is account-wide — the pin removes
  model-mix confounding, it does not add quota.
- LiteLLM routing fix: the gateway branch now applies only to the
  dynamic default (→ `gemini-3.5-flash-lite-free` twin) and to gateway
  alias names (no `/`). Raw OR slugs (`vendor/model[:free]`) always go
  direct to `OR_BASE` — previously an explicit `--or-model` pin on a
  litellm-creds host was forwarded verbatim and 404'd (no such
  `model_name`). The pin now resolves identically on every host.
- `orkey` secret search widened to `litellm-keys.env` /
  `litellm-ada.env` so hosts carrying only gateway env still resolve
  `OPENROUTER_API_KEY` for the direct-OR path.

New job record:
`docs/ssot/jobs/models/2026-11-27-edu-agent-bench-or-model-pin.yml`
(decision, verification, and explicit not-done list).

## Verification

- `python3 -m py_compile scripts/bench-edu-manage.py` — OK
- `python3 -m pytest tests/test_bench_edu_manage_reps.py` — 2 passed
- Pipeline-load smoke (empty `--tasks` filter, no network calls):
  - default → `base=https://openrouter.ai/api/v1`,
    `model=nvidia/nemotron-3.5-super-vl:free`
  - + `LITELLM_*` env → same direct-OR pin (host-independent)
  - `--or-model openrouter/free` + litellm env → gateway +
    `gemini-3.5-flash-lite-free` (legacy path preserved)
  - `--or-model or-free-nemotron-ultra` + litellm env → gateway alias
    passthrough (legacy path preserved)
- Report JSON records the resolved model per lane — A/B outputs
  self-document the pin.
- Commit `b48079d6622` on `dispatch/20261127-144253-pin-a-free-openrouter-model-in`;
  pre-commit SSOT validation + optimization gates passed.

## Not done / next step

No live A/B rerun — the store-aware treatment still owes 3 pinned reps
on mn01 once OR `:free` capacity is confirmed (account cap resets
00:00Z). No deploys: litellm config untouched, no units restarted.
Vendored `bench-edu-manage.py` snapshots under
`scripts/colab/packs/*/inputs/chaba/` are frozen pack inputs for
local-lane runs and were intentionally left as-is.

lessons:
- bench-edu-manage.py's litellm branch forwards `--or-model` verbatim to the gateway — any OR slug (vendor/model) 404s there because litellm only serves declared model_names; '/' in the model string is a reliable discriminator for "raw OR slug → direct".
- The clawbot lane's "unpinned" sentinel was `model == OR_MODEL`; changing a default constant silently re-points that sentinel — check every equality use of a defaulted constant before repurposing it.
- ops-0037's litellm rescue made gateway routing unconditional on creds; pinning required gating it to alias-shaped names only.
- An empty `--tasks __none__` filter runs the whole bench pipeline (imports, corpus, secret loads, lane construction, report write) with zero network calls — cheap way to verify "pipeline loads" in dispatch.
