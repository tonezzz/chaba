# try-hermes — dispatch outcome (run 2, conclusive)

## What was done

Built `scripts/bench-hermes.py` (new reusable harness) and ran a quiet-GPU
bench of `hermes3:8b` vs the live T1 roster on omen (`qwen3:4b`,
`phi3-gguf`): 4 probes × 3 reps × 3 models = 261 sequential calls against
`http://100.75.102.88:11434/api/chat` (temp 0.2, seed 42, 120s timeout).

## Result — AQ PASS, verdict: adopt as T1 tool-calling slot

| probe | hermes3:8b | qwen3:4b | phi3-gguf |
|---|---|---|---|
| toolcall_native | 80% / 14.6s | 80% / 42.3s | unsupported (HTTP 400) |
| toolcall_prompted | 100% / 11.1s | 46.7% / 41.7s | 100% / 8.6s |
| routing | 83.3% / 1.4s | 66.7% / 28.0s | 83.3% / 0.6s |
| reasoning | 57.1% / 0.6s | 42.9% / 34.1s | 85.7% / 1.9s |

Zero errors/timeouts for hermes/qwen3 in the clean run (run-1's
"inconclusive" was confirmed to be GPU contention, not the model).
hermes3:8b is the **only** omen model good at both tool-call arms —
native `<tool_call>` (80%) and prompted-JSON (100%). Latency ~11–15s per
tool call on the shared 4 GB GPU: fine for async agent loops, marginal
interactive. Weak spot: reasoning (57% vs phi3's 86%) — keep reasoning on
phi3.

## Changed / produced

- `scripts/bench-hermes.py` — reusable 4-probe harness (models/probes/reps flags)
- `docs/ssot/jobs/models/2026-10-10-hermes3-t1-eval.yml` — decision record
- `docs/ssot/infrastructure/ssot.model-routing.yml` — hermes3:8b declared in `t1-local-mid` with scope note
- `reports/bench-hermes-20261010.{json,md,log}` — raw results + human report (worktree-local; `reports/` is gitignored — key numbers are duplicated in the jobs yml)
- New card via board API: `hermes-openclaw-slot` — A/B hermes3:8b as OpenClaw local provider vs GhostRoute OR-free rotation

## How to verify

- `python3 scripts/bench-hermes.py --models hermes3:8b --probes toolcall_prompted --reps 1` — expect ~100% score.
- `node scripts/ssot-validate-all.mjs` — all 1970 files valid.
- Card `try-hermes` comms carry the verdict + evidence pointers.

## Card state

Final comms posted with verdict + pointers; dispatcher moves to review.
Follow-up `hermes-openclaw-slot` filed in backlog (not queued — Tony can
dispatch when wanted).

lessons:
- killing a nohup'd python can hit the wrapper and orphan the real child — my restart left TWO bench processes silently racing the GPU and inflating every p50 ~1.5-2x; verify `ps` for orphans, don't trust the echoed pid.
- python under nohup buffers stdout — use `python3 -u` or the log stays empty until exit.
- phi3-gguf's ollama template has no tool block: /api/chat with `tools` returns HTTP 400 — check native-vs-prompted capability per model, don't assume.
- qwen3 think-blocks cost 3-4x wall time AND wreck prompted-JSON fidelity (46.7%) — thinking models are a poor fit for tight-JSON tool loops.
- `reports/` is gitignored in this repo — duplicate durable numbers into docs/ssot/jobs/ yml or they won't merge.
