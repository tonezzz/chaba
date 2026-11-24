#!/usr/bin/env python3
"""Merge a LoRA adapter into its base and save a full HF model dir.

Usage:
  python3 merge_lora.py --base typhoon-ai/typhoon2.5-qwen3-4b \
      --adapter runs/typhoon25-4b-lora --out runs/typhoon25-4b-lora-merged

Then eval it:
  python3 eval_run.py --backend hf --model runs/typhoon25-4b-lora-merged --eval all
Or convert to GGUF for ollama/llama.cpp (llama.cpp convert script or
`ollama create` from a GGUF produced by llama.cpp's convert_hf_to_gguf.py).
"""
import argparse

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--adapter", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    tok = AutoTokenizer.from_pretrained(args.base, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        args.base, torch_dtype=torch.bfloat16, device_map="auto",
        trust_remote_code=True)
    model = PeftModel.from_pretrained(model, args.adapter)
    merged = model.merge_and_unload()
    merged.save_pretrained(args.out, safe_serialization=True)
    tok.save_pretrained(args.out)
    print(f"merged model saved -> {args.out}")


if __name__ == "__main__":
    main()
