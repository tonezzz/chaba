# Outcome: bench-combo-cascade-whisper-piper (2026-10-09)

## What changed
- **Rebuilt the missing harness** — `scripts/voice-bench/` never landed (the idc03
  dispatch worktree for `voice-bench-harness` was swept dirty and nothing was
  committed). Implemented per that card's spec in this worktree:
  `combos.yml`, `bench.py`, `report.py`, `gen_fixtures.py`, `.gitignore`.
- **15 fixtures** under `fixtures/` — 10 English (piper-synthesized, HA commands /
  questions / chit-chat) + 5 Thai (gTTS-synthesized), each with expected
  transcript + expected tool JSON in `manifest.yml`.
- **Bench results** — `scripts/voice-bench/results/cascade-whisper-piper-20261009-065457.json`
  and rendered `reports/voice-fallback/LATEST.md`.
- **Job record** — `docs/ssot/jobs/voice-bench/2026-10-09-cascade-whisper-piper.yml`.
- Tooling in `.bench-tools/` (venv, piper binary, EN voice) is gitignored; fixture
  wavs are committed (small).

## Results (GTX 1650 4GB, ollama phi3-gguf on GPU)

| stt | device | lang | stt ms | llm ms | tts ms | total ms | WER/CER | tool e/p/n |
|---|---|---|---|---|---|---|---|---|
| small | cuda | en | 652 | 13522* | 1900 | 16226 | 0.029 | 5/3/2 |
| small | cuda | th | 814 | 14245* | — | 15367 | 0.120 | 1/0/4 |
| medium | cpu | en | 15248 | 5866 | 1403 | 22668 | 0.045 | 5/2/3 |
| medium | cpu | th | 17227 | 7774 | — | 25154 | 0.137 | 1/0/4 |

*LLM averages include cold-load outliers (21s/39s first calls); warm runs 3-13s.

## Findings
- whisper-small + CUDA is a viable STT (~0.65s); whisper-medium cannot coexist
  with resident phi3 in 4GB VRAM → CPU fallback is 15-20s/fixture, unusable.
- LLM latency dominates the round trip; phi3 emits the right tool ~2/3 of EN
  commands but invents entity_ids (partial matches). Thai input → mostly invalid
  JSON (4/5 none).
- **Thai TTS gap confirmed**: no piper Thai voice exists; TH fixtures ran
  STT+LLM only, tts recorded `skipped`.

## Verify
- `cat reports/voice-fallback/LATEST.md`
- Re-run: `LD_LIBRARY_PATH=.bench-tools/venv/lib/python3.14/site-packages/nvidia/{cublas,cudnn}/lib \
  .bench-tools/venv/bin/python scripts/voice-bench/bench.py --combo cascade-whisper-piper`
- Dry-run schema check: `bench.py --combo cascade-whisper-piper --dry-run`

Committed on branch `dispatch/20261009-063553-bench-combo-cascade-whisper-pi` (not pushed).
