#!/usr/bin/env python3
"""Side-by-side eval for the Thai bakeoff.

Runs the three card-specified eval sets and scores them:
  eval_xlsum_th.jsonl    -> ROUGE-1/2/L (Thai XL-Sum test, summarisation)
  eval_thaiqa_*.jsonl    -> token-F1 + EM + ROUGE-L (ThaiQA-SQuAD, extractive QA)
  eval_scbmt_*.jsonl     -> corpus BLEU + mean sentence chrF++ (SCB-MT en->th)

Backends:
  --backend hf      transformers generate (bf16 on GPU / fp32 on CPU)
  --backend openai  any OpenAI-compatible endpoint (vllm, ollama /v1,
                    llama.cpp --server) — use this to eval deployed GGUFs

Examples:
  python3 eval_run.py --backend hf --model airesearch/LLaMa3-8b-WangchanX-sft-Full
  python3 eval_run.py --backend openai --base-url http://localhost:11434/v1 \
      --model typhoon2.5-qwen3-4b --eval scbmt --limit 50
  python3 eval_run.py --backend hf --model runs/wangchanx-8b-lora-merged --eval all
"""
import argparse
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")

EVALS = {
    "xlsum": ("eval_xlsum_th.jsonl", 256),
    "thaiqa": ("eval_thaiqa_validation.jsonl", 64),
    "scbmt": ("eval_scbmt_en2th.jsonl", 256),
}


# ---------- generation ----------

def clean_output(text):
    """Drop thinking blocks (Qwen3-style) and trailing special tokens."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    text = re.sub(r"<think>.*$", "", text, flags=re.S)
    return text.strip()


def gen_hf(model, tok, messages, max_new, do_sample, temp):
    prompt = tok.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True
    )
    ids = tok(prompt, return_tensors="pt").to(model.device)
    out = model.generate(
        **ids,
        max_new_tokens=max_new,
        do_sample=do_sample,
        temperature=temp if do_sample else None,
        top_p=0.95 if do_sample else None,
        repetition_penalty=1.05,
        pad_token_id=tok.eos_token_id,
    )
    return clean_output(tok.decode(out[0][ids["input_ids"].shape[1]:],
                                   skip_special_tokens=True))


def gen_openai(client, model, messages, max_new, do_sample, temp):
    kw = {}
    if do_sample:
        kw = {"temperature": temp, "top_p": 0.95}
    r = client.chat.completions.create(
        model=model, messages=messages, max_tokens=max_new,
        **kw,
    )
    return clean_output(r.choices[0].message.content or "")


# ---------- Thai-aware tokenization ----------
# rouge_score's built-in tokenizer keeps only [a-z0-9] — Thai text scores 0.
# Use PyThaiNLP newmm word segmentation; fall back to per-char tokens for
# unspaced (Thai) runs so metrics degrade gracefully without the dep.

def thai_tokenize(text):
    try:
        from pythainlp.tokenize import word_tokenize
        return word_tokenize(text, engine="newmm", keep_whitespace=False)
    except Exception:
        toks = []
        for w in text.split():
            if w.isascii():
                toks.append(w)
            else:
                toks.extend(list(w))
        return toks


class ThaiRougeTokenizer:
    def tokenize(self, text):
        return thai_tokenize(text)


_THAI_TOK = ThaiRougeTokenizer()


# ---------- metrics ----------

def norm_squad(s):
    s = s.lower()
    s = re.sub(r"\b(a|an|the)\b", " ", s)
    s = re.sub(r"[^\w\s]", " ", s)
    return " ".join(s.split())


def f1_em(pred, golds):
    """SQuAD-style token F1 + EM over Thai-segmented tokens."""
    pt = thai_tokenize(norm_squad(pred))
    best_f1, em = 0.0, 0.0
    for g in golds:
        gt = thai_tokenize(norm_squad(g))
        common = {}
        for t in pt:
            common[t] = common.get(t, 0) + 1
        overlap = 0
        for t in gt:
            if common.get(t, 0) > 0:
                common[t] -= 1
                overlap += 1
        if overlap == 0:
            f1 = 1.0 if not pt and not gt else 0.0
        else:
            p, r = overlap / len(pt), overlap / len(gt)
            f1 = 2 * p * r / (p + r)
        best_f1 = max(best_f1, f1)
        if pt == gt:
            em = 1.0
    return best_f1, em


def rouge_scores(hyps, refs):
    from rouge_score import rouge_scorer
    sc = rouge_scorer.RougeScorer(
        ["rouge1", "rouge2", "rougeL"], use_stemmer=False,
        tokenizer=_THAI_TOK)
    agg = {"rouge1": 0.0, "rouge2": 0.0, "rougeL": 0.0}
    for h, r in zip(hyps, refs):
        s = sc.score(r, h)  # (reference, prediction)
        for k in agg:
            agg[k] += s[k].fmeasure
    n = max(len(hyps), 1)
    return {k: v / n for k, v in agg.items()}


def mt_scores(hyps, refs):
    import sacrebleu
    bleu = sacrebleu.corpus_bleu(hyps, [refs]).score
    # chrF++: char n-grams order 6 + word n-grams order 2 (Popovic 2017);
    # sentence_chrf takes a *list* of references per hypothesis.
    chrf_vals = [
        sacrebleu.sentence_chrf(h, [r],
                                char_order=6, word_order=2).score
        for h, r in zip(hyps, refs)
    ]
    return {"bleu": bleu, "chrfpp": sum(chrf_vals) / max(len(chrf_vals), 1)}


# ---------- runner ----------

def run_eval(name, rows, generate, limit):
    hyps, refs, extra = [], [], []
    t0 = time.time()
    for i, r in enumerate(rows):
        if limit and i >= limit:
            break
        msgs = r["messages"]
        max_new = EVALS[name][1]
        hyp = generate(msgs, max_new)
        hyps.append(hyp)
        if "references" in r:
            refs.append(r["references"][0] if isinstance(
                r["references"], list) else r["references"])
        if "answers" in r:
            extra.append((hyp, r["answers"]))
        if (i + 1) % 50 == 0:
            print(f"  [{name}] {i+1}/{len(rows)} "
                  f"({(time.time()-t0)/60:.1f} min)", flush=True)
    dt = time.time() - t0

    if name == "xlsum":
        return {"metric": "rouge", **rouge_scores(hyps, refs),
                "n": len(hyps), "secs": round(dt, 1)}
    if name == "thaiqa":
        f1s = [f1_em(h, g) for h, g in extra]
        f1 = sum(x[0] for x in f1s) / max(len(f1s), 1)
        em = sum(x[1] for x in f1s) / max(len(f1s), 1)
        rl = rouge_scores(hyps, [g[0] for _, g in extra])["rougeL"]
        return {"metric": "f1_em_rougeL", "f1": f1, "em": em,
                "rougeL": rl, "n": len(hyps), "secs": round(dt, 1)}
    if name == "scbmt":
        return {"metric": "bleu_chrfpp", **mt_scores(hyps, refs),
                "n": len(hyps), "secs": round(dt, 1)}
    raise ValueError(name)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", choices=["hf", "openai"], required=True)
    ap.add_argument("--model", required=True,
                    help="HF id/dir (hf) or served model name (openai)")
    ap.add_argument("--base-url", default="http://localhost:8000/v1")
    ap.add_argument("--api-key", default="dummy")
    ap.add_argument("--eval", default="all",
                    choices=["all", "xlsum", "thaiqa", "scbmt"])
    ap.add_argument("--limit", type=int, default=0,
                    help="cap items per eval (smoke runs)")
    ap.add_argument("--max-new-tokens", type=int, default=0,
                    help="override per-eval default")
    ap.add_argument("--do-sample", action="store_true",
                    help="sample instead of greedy (not recommended for eval)")
    ap.add_argument("--temperature", type=float, default=0.6)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    wanted = list(EVALS) if args.eval == "all" else [args.eval]
    # resolve thaiqa/scbmt filenames (suffixed by split/direction)
    files = {}
    for name in wanted:
        base = EVALS[name][0]
        if name in ("thaiqa", "scbmt"):
            import glob
            hits = sorted(glob.glob(os.path.join(DATA, base.replace(
                ".jsonl", "_*.jsonl"))))
            if hits:
                base = os.path.basename(hits[0])
            else:
                sys.exit(f"missing data file for {name}: run prep_data.py")
        path = os.path.join(DATA, base)
        if not os.path.exists(path):
            sys.exit(f"missing {path} — run prep_data.py first")
        files[name] = [json.loads(l) for l in open(path, encoding="utf-8")]

    # build generator
    if args.backend == "hf":
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        tok = AutoTokenizer.from_pretrained(args.model,
                                            trust_remote_code=True)
        dtype = torch.bfloat16 if torch.cuda.is_available() else torch.float32
        model = AutoModelForCausalLM.from_pretrained(
            args.model, torch_dtype=dtype, device_map="auto",
            trust_remote_code=True)
        model.eval()

        def generate(msgs, max_new):
            mn = args.max_new_tokens or max_new
            return gen_hf(model, tok, msgs, mn, args.do_sample,
                          args.temperature)
        tag = args.model
    else:
        from openai import OpenAI
        client = OpenAI(base_url=args.base_url, api_key=args.api_key)

        def generate(msgs, max_new):
            mn = args.max_new_tokens or max_new
            return gen_openai(client, args.model, msgs, mn,
                              args.do_sample, args.temperature)
        tag = f"{args.base_url}::{args.model}"

    results = {"model": tag, "backend": args.backend,
               "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
               "evals": {}}
    for name in wanted:
        print(f"=== {name} ({len(files[name])} items) ===", flush=True)
        results["evals"][name] = run_eval(name, files[name], generate,
                                          args.limit)
        print(json.dumps(results["evals"][name], ensure_ascii=False),
              flush=True)

    out = args.out or os.path.join(
        HERE, f"results-{tag.replace('/', '_').replace(':', '_')}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
