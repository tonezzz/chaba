# Dispatch outcome — openchamber-multirun-adobe-stock-prompts

**Result: COMPLETE.** The same read-only Adobe Stock campaign brief was
run through three approved OpenCode models, each fully isolated from
board and filesystem mutation; all three passed the held-out verifier.
Comparison artifact recommends `litellm/or-free-nemotron-ultra`.

## What was done

- Froze the live campaign state (gdrive
  `ada-nest/adobe-stock/campaigns/AS-2026-11-05-REMOTE-WORK-001` —
  SESSION.json, RUN.json, index, QC review, 16 manifests, status
  receipt) into `evals/adobe-stock-multirun/input/` and distilled it
  via `build_input.py` into `input.json` — embedded verbatim in
  `brief_template.md`, so every arm got byte-identical input (prompt
  sha256 `2bf75546…` on all three, recorded in comparison.json).
- Built a deny-all-tools harness (`run.py`): per-arm rendered
  `opencode.json` disables every builtin tool, denies all permissions,
  mounts zero MCP, disables builtin agents, and runs
  `opencode run --standalone` in an empty scratch dir. The model
  cannot mutate board or filesystem by construction; the event audit
  confirms zero tool calls, zero denials, zero mutating commands, zero
  write attempts on every arm.
- Ran 3 approved models (union of enabled-profile `model.allowed`
  lists): `litellm/or-free-nemotron-ultra` (OR :free),
  `litellm/or-gemini-3.5-flash` (OR paid), `litellm/gemini-3.5-flash-lite`
  (direct). All verifier-pass with identical mechanical scores
  (relevance/provenance/missing-preview/policy = 5/5/5/5).
- Wrote held-out `verify.py` scoring coverage, hallucinated ids,
  provenance field-exactness (45/45 fields matched per arm),
  missing-preview F1 vs ground truth (1.0), qc_decision honoring, and
  the policy block.

## Findings

- **Recommended: `litellm/or-free-nemotron-ultra`** — $0, 177.7s,
  textbook qc_decision→decision mapping, most defensible upload pick
  (`comparison-e-gemini-fix3-region`). `or-gemini-3.5-flash` is the
  balanced paid alternative (53.8s, caught an aspect-ratio defect, but
  contradicted itself on upload_candidate). `gemini-3.5-flash-lite` is
  fastest/cheapest ($0.0053, 32.9s) but shallowest — picked the
  baseline asset as upload candidate against its own QC note.
- Rejected candidates (documented in run.py + job doc):
  `litellm/gemini-3.5-flash` → provider.no-route under opencode v2.4.1
  (raw API works; models.dev registry gap); all `opencode/*` Zen free
  models → provider.free-limit; `litellm/gemini-3.5-flash-free` →
  proxy timeout.
- Verifier caveat found and fixed mid-run: the first input lacked
  canonical `qc_decision` fields, leaving HARD_REJECTS empty (vacuous
  check). `build_input.py` now emits explicit verdicts and all arms
  were re-run on the enriched identical input.

## Where the deliverables are

- Comparison artifact: `evals/adobe-stock-multirun/reports/comparison.md`
  + `comparison.json` (identical-input hashes, per-arm outputs refs,
  verifier scores, recommended model + rationale)
- Per-arm evidence: `evals/adobe-stock-multirun/runs/<arm>/`
  (opencode.json, prompt.md, events.jsonl, artifact.out, verdict.json,
  run.json)
- Methodology: `evals/adobe-stock-multirun/README.md`,
  `build_input.py`, `verify.py`, `run.py`
- Trail: `docs/ssot/jobs/devnest/2026-11-25-adobe-stock-multirun-opencode-models.yml`

## How to verify

```
cd evals/adobe-stock-multirun
python3 verify.py runs/or-free-nemotron-ultra   # -> verdict pass, 5/5/5/5
python3 run.py --compare                        # rebuilds reports/ from run.json
cat reports/comparison.md
```

No run uploaded, generated, licensed, or mutated cards — confirmed by
zero tool calls/denials/mutations in every arm's events.jsonl audit.

lessons:
- `litellm/gemini-3.5-flash` works via raw chat-completions but opencode v2.4.1 returns provider.no-route — models.dev registry gap; smoke-test every candidate model before committing arms.
- All `opencode/*` Zen free models were rate-limited (provider.free-limit) on 2026-11-25 — don't assume Zen free capacity.
- A held-out verifier with empty ground truth passes vacuously — sanity-check HARD_REJECTS-style sets are non-empty before trusting verifier_pass.
- Deny-all agent config (all tools off + permission '*':deny + zero MCP + scratch cwd) is the cleanest read-only isolation for brief-evals; stronger than any shipped profile.
- or-free-nemotron-ultra prompt-caches heavily (26K cache-read vs 8.6K fresh input) — $0 but ~3-5x slower wall time than Gemini flash arms.
