# opencode-lane Status Report - 2026-10-30

## Existing Profiles & Artifact Modes

| Profile          | Artifact Mode   | Description |
|------------------|-----------------|-------------|
| ops-readonly     | JSON (message)  | Emits JSON reports via message mode to `evals/opencode-lane/out/` and `reports/` |
| doc-draft        | Markdown (message) | Produces markdown artifacts via message mode to `docs/reports/` |
| artifact-write   | File (direct)   | Writes files directly to `evals/opencode-lane/out/`, `reports/`, and `docs/reports/` |

## Verified Pilot Merges

- Merged `562d54fdd` (health JSON) via `ops-readonly`
- Merged `ddda1db1b` + `c1813b5a0` (docs) via `doc-draft` and `artifact-write`

## Working Models

- `litellm/or-gemini-3.5-flash` (OPS-0998)
- `litellm/ollama-qwen32b-kkmac` (OPS-1014)
- `litellm/ollama-qwen38b-kkmac` (OPS-1024, default for `doc-draft`)

## Branch-Code Status

- `branch-code` is **disabled** pending S5 gate approval

## Model Notes

- `qwen38b-kkmac` shows ~4x speed over `qwen32b-kkmac` with better instruction-following
- `gemini-3.5-flash-lite` and `or-gemini-3.5-flash-lite` exhibit mid-agentic-loop failures
- `or-free-nemotron-nano` fails due to bash denials in agentic loop

## Verifier Notes

- Sentinels only check for presence, not semantic accuracy
- Human review still required for final doc quality verification

