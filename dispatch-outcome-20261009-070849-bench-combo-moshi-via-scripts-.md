# dispatch-outcome: bench-combo-moshi

Card: `voice-combo-moshi` — bench kyutai-labs/moshi through
`scripts/voice-bench/bench.py`, English fixtures only, tool_call expected
none.

## Result: benched (CPU-only — GPU too small)

- moshi 0.2.13 (`kyutai/moshiko-pytorch-bf16`, ~15GB weights) installed in
  worktree venv `.tmp-moshi/venv` (uv, py3.12, torch 2.9.1+cu128).
- **Hardware verdict:** tony-omen's GTX 1650 (4GB, ~2.5GB free) cannot run
  moshi — bf16 needs ~15GB VRAM; even the candle/moshi-server q4 variant
  (~4.5GB weights + mimi + KV) exceeds it. Rust server also lacks a
  toolchain here. So the PyTorch server ran on `--device cpu`
  (i7-9750H, weights resident via swap, ~140% CPU).
- `combos.yml` gained a `moshi` entry (runtime local, host_labels [gpu],
  endpoint `http://127.0.0.1:8999`); `scripts/voice-bench/moshi_adapter.py`
  is new — it owns the `moshi.server` subprocess and exposes the harness
  `POST /bench` contract over moshi's ws protocol (`\x01`+opus in/out,
  `\x02` text tokens on `/api/chat`), streaming fixtures realtime-paced
  and collecting a ≤90s reply window.
- bench.py ran unmodified: 10 en fixtures `ok`; 10 th appended as
  `status=n/a` (Moshi is English-only).
- Numbers: mean_ttfa **50.6s** (10.4–113.6s — CPU-bound floor, NOT the
  ~200ms moshi achieves on real GPUs), mean_total 218s (includes the
  reply window; moshi keeps talking), WER n/a (s2s model replies speech —
  `transcript` holds moshi's reply text, e.g. "Hey,", "Hi there"),
  tool_call **none** on all 7 fixtures expecting calls — by design, that
  is the finding: moshi has no function-calling surface at all.
- Assessment written to `docs/ssot/jobs/voice/2026-10-09-voice-combo-moshi.yml`:
  far from Ada/GEV needs — no tool plumbing, English-only, weak
  prompting; at most a conversational frontend in front of a real
  orchestrator. Rerun on a ≥8GB-GPU runner would yield real ttfa; the
  combos.yml entry + adapter are already wired (`MOSHI_DEVICE` env).

## Changed / added

- `scripts/voice-bench/combos.yml` — `moshi` combo entry
- `scripts/voice-bench/moshi_adapter.py` — new transport adapter
- `scripts/voice-bench/results/moshi-*.json` — two runs (first is the
  instant-flood attempt, superseded by `…004739Z`)
- `reports/voice-fallback/LATEST.md`, `trend.md` — regenerated
- `docs/ssot/jobs/voice/2026-10-09-voice-combo-moshi.yml` — job record
- `.tmp-moshi/` — untracked venv (~5GB) left for reuse; safe to delete

Not committed, not pushed. Board comment posted on `voice-combo-moshi`.

## How to verify

- `cat scripts/voice-bench/results/moshi-20261009T004739Z.json`
- `cat reports/voice-fallback/LATEST.md`
- Rerun (needs moshi env): `MOSHI_DEVICE=cpu
  MOSHI_PYTHON=.tmp-moshi/venv/bin/python python3
  scripts/voice-bench/bench.py --combo moshi --fixtures en-chat-hello
  --timeout 700`
