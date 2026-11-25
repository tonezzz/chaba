# adobe-stock-multirun — OpenCode model comparison eval

Card: `openchamber-multirun-adobe-stock-prompts` (OPS-1200) ·
Run: 2026-11-25 on idc02 · Status: **done — 3/3 arms verifier-pass**

Runs ONE identical read-only Adobe Stock campaign brief through up to
three approved OpenCode models and compares asset relevance,
provenance preservation, missing-preview detection, policy compliance,
and token/cost/latency. Recommended profile: **`litellm/or-free-nemotron-ultra`**.

## Layout

- `input/` — frozen campaign snapshot (gdrive
  `ada-nest/adobe-stock/campaigns/AS-2026-11-05-REMOTE-WORK-001`):
  SESSION.json, RUN.json, assets.json index, campaign-status receipt,
  40-qc-review.md, multi-run-contract.md, 16 per-asset manifests.
- `build_input.py` — distills `input/` into `input.json` (the JSON
  embedded verbatim in the prompt). Deterministic; `QC_DECISIONS` is
  the canonical human-verdict table used as ground truth.
- `brief_template.md` — the identical task + output contract
  (`{{INPUT_JSON}}` placeholder).
- `verify.py` — held-out mechanical verifier (required keys, asset
  coverage, no hallucinated ids/provenance, qc_decision honored,
  missing-preview F1 vs ground truth, policy block).
- `run.py` — harness: renders a deny-all-tools `opencode.json` per arm,
  runs `opencode run --format json --standalone` in an empty scratch
  cwd, audits events (tokens/tools/denials/mutations), extracts the
  message-mode JSON artifact, verifies, emits `run.json`.
- `runs/<arm>/` — per-arm evidence: opencode.json, prompt.md,
  events.jsonl, stderr.log, artifact.out, final-message.md,
  verdict.json, run.json.
- `reports/comparison.{json,md}` — the comparison artifact.

## Isolation

Every arm runs an agent with **all builtin tools disabled**
(read/bash/write/edit/webfetch/task/...), `permission: "*": deny`,
zero MCP, builtin agents disabled, and an empty scratch project dir —
the model cannot touch the board, the filesystem, or any service.
Audit confirms zero tool calls, zero denials, zero mutating commands,
zero write attempts on all three arms.

## Arms (approved = enabled-profile `model.allowed` union)

| arm | model | route | cost |
|---|---|---|---|
| or-free-nemotron-ultra | `litellm/or-free-nemotron-ultra` | LiteLLM→OpenRouter :free | $0 |
| or-gemini-3.5-flash | `litellm/or-gemini-3.5-flash` | LiteLLM→OpenRouter | unpriced in lane_gate table |
| gemini-3.5-flash-lite | `litellm/gemini-3.5-flash-lite` | LiteLLM direct | $0.0053 |

Models smoke-tested and rejected 2026-11-25: `litellm/gemini-3.5-flash`
(provider.no-route under opencode v2.4.1 despite working via raw API —
models.dev registry gap), all `opencode/*` Zen free models
(provider.free-limit), `litellm/gemini-3.5-flash-free` (proxy timeout).

## Reproduce

```bash
cd evals/adobe-stock-multirun
python3 build_input.py     # refresh input.json from input/ snapshot
python3 run.py             # all arms (~5 min total)
python3 run.py --compare   # rebuild reports/comparison.{json,md}
python3 verify.py runs/<arm>   # re-check one arm
```

Note: `input/` is a point-in-time snapshot — the live campaign keeps
moving (reindex-sync.timer). The frozen copy is the eval input; do not
"fix" it to track live state.
