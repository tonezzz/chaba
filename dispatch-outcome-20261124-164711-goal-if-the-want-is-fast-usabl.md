# Dispatch outcome — thai-llm-finetune-experiment (Typhoon + WangchanX)

Card: `thai-llm-finetune-experiment-typhoon-wan-9ef801` (OPS-0760)
Host: idc02 (CPU-only, 4 vCPU, no GPU) — desk bakeoff + verified harness + live CPU smoke, mirroring the NCM recon/toy-train split.

## What changed / was found

**Verdict (gate answer):** yes — fast/usable Thai generation TODAY is a small
Thai AR model, not NCM. Verified live: `typhoon-ai/typhoon2.5-qwen3-4b` official
Q4_K_M GGUF (2.5GB, Apache-2.0) ran on this CPU-only box via llama-cpp-python —
fluent Thai intro, accurate Thai news summary, correct EN→TH translation at
~0.4-0.6 tok/s under load (~4.3GB RSS). "Usable" = deploy now on ollama;
"fast" still wants the GPU lane (omen/idc).

**Base picks:** Typhoon = `typhoon2.5-qwen3-4b` (newest instruct, Qwen3-4B,
256k ctx, official GGUF). WangchanX = `airesearch/LLaMa3-8b-WangchanX-sft-Full`
(canonical NECTEC instruct, tops ThaiLLM-Leaderboard XL-Sum Thai ROUGE-L 28.2,
#2 ThaiQA ROUGE-2 66.9).

**Comparison table:** built from published ThaiLLM-Leaderboard/SEACrowd
results (13 models × XL-Sum-th / ThaiQA-iApp / FLORES en→th+th→en) — full table
in `experiments/thai-llm-ft/README.md` and the jobs yml. Read: WangchanX/LION
own Thai NLG; Typhoon owns en→th MT and is the actively-developed family.

## Deliverables (in worktree)

- `experiments/thai-llm-ft/` — runnable experiment pack:
  - `prep_data.py` — builds SFT slice (8k of airesearch/wangchanx-seed-free-
    synthetic-instruct-thai-120k) + 3 eval sets (XL-Sum th 826, ThaiQA-SQuAD
    74, SCB-MT en→th 1k). **Ran end-to-end, all files verified.**
  - `train_lora.py` — QLoRA SFT (unsloth 4-bit preferred / peft+bnb fallback),
    completion-only loss, chat-template aware.
  - `merge_lora.py`, `eval_run.py` (hf + OpenAI-compatible backends; strips
    <think>; Thai-aware ROUGE via PyThaiNLP newmm; SQuAD-F1/EM; BLEU+chrF++),
    `smoke_gguf.py`, `requirements.txt`, `README.md` (design + commands +
    published table + decision rule).
- `docs/ssot/jobs/experiments/2026-11-24-thai-llm-ft-bakeoff.yml` — durable
  findings doc: picks, published baselines, metric caveats, GPU sizing,
  deploy lane, remaining steps.
- `experiments/thai-llm-ft/.venv/` + `data/` + `models/` are gitignored
  (2.5GB GGUF not committed).

## Result / how to verify

- Data pack verified: `data/*.jsonl` row counts 200(sft smoke)/826/74/50.
- Metrics unit-checked (Thai ROUGE nonzero, F1/EM, BLEU/chrF++ sanity).
- Smoke verified: Thai outputs fluent/correct (see jobs yml `smoke_test`).
- NOT done (needs GPU): actual LoRA runs + side-by-side scores. 4B QLoRA
  ~6GB VRAM (omen 4GB marginal w/ unsloth; T4 fine); 8B needs ≥12GB.
  Commands in `experiments/thai-llm-ft/README.md` §Pipeline.
- Deploy lane if winner emerges: official Typhoon GGUF → ollama on omen or
  idc shelf; WangchanX via mradermacher GGUF or merge+convert.

## lessons:

- `rouge_score` default tokenizer keeps only `[a-z0-9]` — Thai text scores 0.0; must inject a Thai-aware tokenizer (PyThaiNLP `newmm` + `thainlp` corpus pkg).
- `datasets>=3` rejects script-based datasets (`pythainlp/thaiqa_squad`); use parquet mirrors (`lighteval/thaiqa_squad_fixed`).
- `hf_hub_download` defaults `repo_type="model"` — dataset repos need `repo_type="dataset"` or you get a misleading 401.
- GGUF chat templates can leak literal `<s>`/`[/INST]` tokens through llama-cpp-python `create_chat_completion` — cosmetic, strip in post.
- CPU smoke of a 4B Q4 GGUF is viable for qualitative checks (~0.5 tok/s under load) but stdout is block-buffered through pipes — use `python -u` or `flush=True`.
