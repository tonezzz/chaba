# Thai LLM fine-tune bakeoff — Typhoon-2.5 vs WangchanX

Card: `thai-llm-finetune-experiment-typhoon-wan-9ef801` (OPS-0760)
Sibling track: OPS-0750 NCM toy-train (`docs/ssot/jobs/experiments/2026-10-20-ncm-thai-*.yml`)
Runbook/result doc: `docs/ssot/jobs/experiments/2026-11-24-thai-llm-ft-bakeoff.yml`

**Question:** if the want is *fast/usable Thai generation today*, does a small
Thai AR model + light LoRA/SFT beat rebuilding NCM — and which family wins?

## Base picks (one per family)

| lane | model | base arch | params | license | why |
|---|---|---|---|---|---|
| Typhoon | `typhoon-ai/typhoon2.5-qwen3-4b` | Qwen3 | 4B | Apache-2.0 | newest Typhoon instruct (2026-06), 256k ctx, function calling, official GGUF (`typhoon2.5-qwen3-4b-gguf`, q4_k_m ≈ 2.5 GB) |
| WangchanX | `airesearch/LLaMa3-8b-WangchanX-sft-Full` | Llama-3 | 8B | llama3 | canonical NECTEC/VISTEC WangchanX instruct; tops ThaiLLM-Leaderboard XL-Sum Thai (ROUGE-L 28.2) and #2 ThaiQA ROUGE-2 (66.9) |

Notes:
- Typhoon alternates considered: `typhoon2-qwen2.5-7b-instruct` (prev gen),
  `llama3.1-typhoon2-8b-instruct`, `typhoon2.1-gemma3-4b`. Picked 2.5-4B for
  the "fast/usable TODAY" goal: smallest newest-gen, official GGUF, fits
  4 GB VRAM QLoRA and ~3 GB RAM/VRAM deploy.
- WangchanX alternates: `LLaMa3-8b-WangchanX-sft-Demo` (small-data demo),
  `airesearch/*-cpt-sea-lionv2-base-*` / `gemma-2-9b-alpaca-th-*` (WangchanX
  pipeline experiments on newer bases, 2025-07/08, no canonical instruct
  release). `sft-Full` is the released flagship.
- Size asymmetry (4B vs 8B) is intentional — it mirrors what each family
  actually ships as "the usable instruct". Per-token latency differs; the
  comparison table records both quality and deploy footprint.

## SFT slice

`airesearch/wangchanx-seed-free-synthetic-instruct-thai-120k` (MIT,
118,898 rows, instruction/context/output) — the same seed-free synthetic
mix the WangchanX pipeline trains on, so the LoRA step measures *additional*
Thai-instruct adaptation on top of each family's own recipe. Default 8k
seeded sample (`--sft-n`).

## Eval (card-specified)

| eval | data | metric |
|---|---|---|
| XL-Sum Thai | `csebuetnlp/xlsum` `thai_XLSum_v2.0.tar.bz2` test (826) | ROUGE-1/2/L, PyThaiNLP-newmm tokens |
| ThaiQA | `lighteval/thaiqa_squad_fixed` validation (74; parquet mirror of `pythainlp/thaiqa_squad`) | token-F1 + EM + ROUGE-L |
| SCB MT | `pythainlp/scb-mt-en-th-2020_mt-opus` test, seeded 1k en→th | corpus BLEU + mean sentence chrF++ |

Metric caveats (verified 2026-11-24):
- `rouge_score` default tokenizer strips Thai (`[a-z0-9]` only) → scores 0.
  Harness uses PyThaiNLP `newmm` segmentation (`thainlp` corpus pkg),
  per-char fallback.
- sacrebleu BLEU on unspaced Thai degenerates (1 whitespace token/sentence);
  chrF++ (char n-grams) is the robust primary for Thai MT. BLEU still
  reported for comparability — treat deltas, not absolutes.
- ThaiQA-SQuAD validation is only 74 items — noisy; iApp-SQuAD
  (SEACrowd `iapp_squad`) is the leaderboard's ThaiQA proxy if a bigger
  set is wanted later.

## Pipeline

```bash
cd experiments/thai-llm-ft
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# 1. data pack (CPU)
.venv/bin/python prep_data.py                      # 8k SFT + full evals
.venv/bin/python prep_data.py --sft-n 8000 --mt-n 1000

# 2. LoRA SFT — GPU host (omen 4GB: unsloth 4-bit; ~16GB: peft bf16)
.venv/bin/python train_lora.py --model typhoon-ai/typhoon2.5-qwen3-4b \
    --data data/sft_train.jsonl --out runs/typhoon25-4b-lora
.venv/bin/python train_lora.py --model airesearch/LLaMa3-8b-WangchanX-sft-Full \
    --data data/sft_train.jsonl --out runs/wangchanx-8b-lora

# 3. merge + eval — same script for base instruct, merged LoRA, GGUF deploy
.venv/bin/python merge_lora.py --base <model> --adapter runs/<run> --out runs/<run>-merged
.venv/bin/python eval_run.py --backend hf --model <model-or-merged> --eval all
.venv/bin/python eval_run.py --backend openai --base-url http://<host>:11434/v1 \
    --model <ollama-model> --eval all        # deployed GGUF lane
```

GPU sizing (QLoRA, seq 2048, bs 4×accum 8):
- 4B: ~6 GB VRAM — fits omen GTX 1650 4GB only with unsloth + smaller
  bs/seq; comfortable on any 8 GB+ card or rented T4/L4.
- 8B: ~10-12 GB VRAM — needs ≥12 GB (rented T4 16GB ok); omen 4GB NOT viable
  for 8B LoRA. CPU alternative: days, not recommended.

## Decision rule

Report per model: instruct-baseline score AND +LoRA score (Δ). Verdict:
- If Typhoon2.5-4B +LoRA ≥ WangchanX-8B ± noise on XL-Sum/ThaiQA and wins
  MT → deploy Typhoon GGUF (Apache-2.0, official quant, smallest).
- If WangchanX-8B wins NLG clearly → it's the quality pick but heavier
  (8B, llama3 license); deploy only if the NLG gap justifies 2× footprint.
- If Δ(LoRA) ≈ 0 on both → skip fine-tuning entirely; the want is already
  met by instruct baselines → deploy winner GGUF, close experiment.

## Published baselines (ThaiLLM-Leaderboard / SEACrowd harness, fetched 2026-11-24)

| model | XL-Sum th R1/R2/RL | ThaiQA(iApp) R2 | FLORES en→th BLEU/chrF++ | FLORES th→en BLEU/chrF++ |
|---|---|---|---|---|
| Gemma2-9B-WangchanLIONv2-instruct | 37.4/16.5/28.0 | 71.2 | 25.8/52.2 | 52.6/59.4 |
| **LLaMa3-8B-WangchanX-sft-Full** | **37.6/16.4/28.2** | **66.9** | 22.9/50.2 | 48.5/55.3 |
| llama3.1-typhoon2-8b-instruct | 30.3/10.6/21.0 | 63.2 | 27.4/52.7 | 50.6/58.4 |
| llama3.2-typhoon2-3b-instruct | 31.2/11.1/21.7 | 57.3 | 24.3/50.7 | 49.6/56.8 |
| llama3.2-typhoon2-1b-instruct | 26.7/9.5/18.7 | 48.4 | 18.7/43.3 | 42.5/50.9 |
| typhoon2-qwen2.5-7b-instruct | 26.5/9.6/17.7 | 43.1 | **27.7/54.3** | 49.3/58.8 |
| Pathumma-llm-text-1.0.0 (Qwen2.5-7B) | 24.9/9.7/16.9 | 34.6 | 26.7/53.0 | 52.8/59.7 |
| openthaigpt1.5-14b-instruct | 28.9/10.1/19.5 | 28.1 | 22.4/48.6 | 48.3/59.5 |
| openthaigpt1.5-7b-instruct | 27.0/9.3/18.1 | 25.8 | 20.9/45.0 | 46.1/57.3 |
| openthaigpt-1.0.0-7b-chat | 24.6/6.6/16.7 | 36.8 | 18.4/44.9 | 15.9/24.3 |
| Llama-3.1-8B-ThaiInstruct | 25.4/9.1/17.2 | 27.6 | 17.3/42.4 | 28.7/31.3 |
| Qwen2.5-7B-ThaiInstruct | 22.3/8.5/15.1 | 15.4 | 11.2/39.3 | 35.3/53.0 |

Read: WangchanX/LION own Thai NLG (news-domain summarisation + extractive
QA); Typhoon owns en→th MT and is the actively-developed family
(typhoon2.5-qwen3-4b post-dates this leaderboard snapshot — expect ≥
typhoon2-qwen2.5-7b). KhanomTanLLM 1B/3B scored ~0 (broken eval outputs).

Source: `huggingface.co/datasets/ThaiLLM-Leaderboard/results` per-model
`results.json` (NLG category), cached locally at dispatch time.

## Live smoke test (2026-11-24, idc02 CPU-only)

`typhoon2.5-qwen3-4b-q4_k_m.gguf` (official, 2.5GB) via llama-cpp-python
0.3.38, 4 threads, temp 0 — fluent Thai intro, accurate Thai news summary,
correct EN→TH translation at ~0.4-0.6 tok/s under host load (RSS ~4.3GB).
Confirms the instruct baseline is usable Thai TODAY; "fast" still wants the
GPU lane. Reproduce: `smoke_gguf.py models/<file>.gguf`.
