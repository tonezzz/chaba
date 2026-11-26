#!/usr/bin/env python3
"""Light LoRA/QQLoRA SFT for the Thai bakeoff.

Trains a LoRA adapter on the Thai instruction slice (data/sft_train.jsonl,
{messages:[...]}) using unsloth when available, else plain peft+TRL.
Completion-only loss: prompt tokens are masked, only assistant tokens train.

Targets:
  - typhoon-ai/typhoon2.5-qwen3-4b      (Qwen3-4B, Apache-2.0)
  - airesearch/LLaMa3-8b-WangchanX-sft-Full (Llama-3-8B)

Both fit a 4-8GB GPU in 4-bit QLoRA (unsloth) or ~16GB in bf16 LoRA.

Usage:
  python3 train_lora.py --model typhoon-ai/typhoon2.5-qwen3-4b \
      --data data/sft_train.jsonl --out runs/typhoon25-4b-lora
  python3 train_lora.py --model airesearch/LLaMa3-8b-WangchanX-sft-Full \
      --data data/sft_train.jsonl --out runs/wangchanx-8b-lora

Merge + export for eval/deploy afterwards:
  python3 merge_lora.py --base <model> --adapter runs/<run> --out runs/<run>-merged
"""
import argparse
import json
import os


def load_rows(path):
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            rows.append(json.loads(line))
    return rows


def render(tokenizer, messages, train=True):
    """-> (prompt_text, completion_text) using the model's own chat template."""
    prompt_msgs = messages[:-1]
    answer = messages[-1]["content"]
    prompt = tokenizer.apply_chat_template(
        prompt_msgs, tokenize=False, add_generation_prompt=True
    )
    eos = tokenizer.eos_token or ""
    return prompt, answer + eos


def make_dataset(tokenizer, rows, max_len):
    from datasets import Dataset

    prompts, completions = [], []
    for r in rows:
        p, c = render(tokenizer, r["messages"])
        prompts.append(p)
        completions.append(c)
    ds = Dataset.from_dict({"prompt": prompts, "completion": completions})
    return ds


def train_unsloth(args, tokenizer):
    from unsloth import FastLanguageModel
    from trl import SFTConfig, SFTTrainer

    model, tok = FastLanguageModel.from_pretrained(
        model_name=args.model,
        max_seq_length=args.max_len,
        load_in_4bit=True,
        trust_remote_code=True,
    )
    model = FastLanguageModel.get_peft_model(
        model,
        r=args.r,
        lora_alpha=args.lora_alpha,
        lora_dropout=0.0,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
        use_gradient_checkpointing="unsloth",
    )
    rows = load_rows(args.data)
    ds = make_dataset(tok, rows, args.max_len)

    cfg = SFTConfig(
        output_dir=args.out,
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.bs,
        gradient_accumulation_steps=args.accum,
        learning_rate=args.lr,
        lr_scheduler_type="cosine",
        warmup_ratio=0.03,
        logging_steps=20,
        save_strategy="epoch",
        bf16=True,
        max_length=args.max_len,
        completion_only_loss=True,
        report_to="none",
        seed=20261124,
    )
    trainer = SFTTrainer(model=model, args=cfg, train_dataset=ds,
                         processing_class=tok)
    trainer.train()
    model.save_pretrained(args.out)
    tok.save_pretrained(args.out)
    print(f"adapter saved -> {args.out}")


def train_peft(args):
    """Fallback: plain transformers+peft+trl, bf16/fp16, no unsloth."""
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from trl import SFTConfig, SFTTrainer

    bnb = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
    )
    tok = AutoTokenizer.from_pretrained(args.model, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        args.model, quantization_config=bnb, device_map="auto",
        trust_remote_code=True,
    )
    model = prepare_model_for_kbit_training(model)
    lora = LoraConfig(
        r=args.r, lora_alpha=args.lora_alpha, lora_dropout=0.0,
        bias="none", task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
    )
    model = get_peft_model(model, lora)
    model.print_trainable_parameters()

    rows = load_rows(args.data)
    ds = make_dataset(tok, rows, args.max_len)
    cfg = SFTConfig(
        output_dir=args.out,
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.bs,
        gradient_accumulation_steps=args.accum,
        learning_rate=args.lr,
        lr_scheduler_type="cosine",
        warmup_ratio=0.03,
        logging_steps=20,
        save_strategy="epoch",
        bf16=True,
        max_length=args.max_len,
        completion_only_loss=True,
        report_to="none",
        seed=20261124,
    )
    trainer = SFTTrainer(model=model, args=cfg, train_dataset=ds,
                         processing_class=tok)
    trainer.train()
    model.save_pretrained(args.out)
    tok.save_pretrained(args.out)
    print(f"adapter saved -> {args.out}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--data", default=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "data", "sft_train.jsonl"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--epochs", type=float, default=2.0)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--r", type=int, default=16)
    ap.add_argument("--lora-alpha", type=int, default=32)
    ap.add_argument("--max-len", type=int, default=2048)
    ap.add_argument("--bs", type=int, default=4)
    ap.add_argument("--accum", type=int, default=8)
    ap.add_argument("--backend", choices=["auto", "unsloth", "peft"],
                    default="auto")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    if args.backend == "unsloth":
        train_unsloth(args, None)
        return
    try:
        import unsloth  # noqa: F401
        train_unsloth(args, None)
    except ImportError:
        train_peft(args)


if __name__ == "__main__":
    main()
