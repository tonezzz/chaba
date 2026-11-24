#!/usr/bin/env python3
"""Build the Thai LLM FT experiment data pack.

Outputs (under data/):
  sft_train.jsonl     {"prompt","completion"} Thai instruction slice for LoRA/SFT
  eval_xlsum_th.jsonl {"id","messages","references"}  Thai XL-Sum test (summarisation)
  eval_thaiqa.jsonl   {"id","messages","answers"}     ThaiQA-SQuAD validation (extractive QA)
  eval_scbmt_en2th.jsonl {"id","messages","references"} SCB-MT-2020 en->th subsample

Everything is deterministic (fixed seeds) so runs are comparable.

Usage:
  pip install -r requirements.txt
  python3 prep_data.py                 # full pack
  python3 prep_data.py --sft-n 8000 --mt-n 1000 --qa-split validation
"""
import argparse
import io
import json
import os
import tarfile
import random

from huggingface_hub import hf_hub_download

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
SEED = 20261124

SFT_DS = "airesearch/wangchanx-seed-free-synthetic-instruct-thai-120k"
# pythainlp/thaiqa_squad is script-only (unloadable on datasets>=3);
# lighteval/thaiqa_squad_fixed is the same ThaiQA-SQuAD data as parquet.
THAIQA_DS = "lighteval/thaiqa_squad_fixed"
THAIQA_CONFIG = "default"
SCBMT_DS = "pythainlp/scb-mt-en-th-2020_mt-opus"
XLSUM_REPO = "csebuetnlp/xlsum"
XLSUM_THAI = "data/thai_XLSum_v2.0.tar.bz2"


def wjsonl(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"wrote {path}: {len(rows)} rows")


def build_sft(n, out):
    """Seeded slice of the WangchanX seed-free synthetic Thai instruct corpus.

    Source fields: instruction, context, output, type, rating, ...
    We keep instruction+context as the user turn and output as assistant.
    """
    from datasets import load_dataset

    ds = load_dataset(SFT_DS, split="train")
    rng = random.Random(SEED)
    idx = list(range(len(ds)))
    rng.shuffle(idx)

    rows = []
    for i in idx:
        if len(rows) >= n:
            break
        r = ds[i]
        instr = (r.get("instruction") or "").strip()
        ctx = (r.get("context") or "").strip()
        answer = (r.get("output") or "").strip()
        if not instr or not answer or len(answer) < 10:
            continue
        user = instr if not ctx else f"{instr}\n\n{ctx}"
        rows.append({
            "messages": [
                {"role": "user", "content": user},
                {"role": "assistant", "content": answer},
            ],
            "type": r.get("type", ""),
        })
    wjsonl(out, rows)


def xlsum_rows():
    """Yield (id, article, summary) from the Thai XL-Sum tarball on HF hub."""
    path = hf_hub_download(XLSUM_REPO, XLSUM_THAI, repo_type="dataset")
    with tarfile.open(path, "r:bz2") as tf:
        for split in ("test", "val"):
            member = f"./thai_{split}.jsonl"
            try:
                f = tf.extractfile(member)
            except KeyError:
                f = tf.extractfile(member.lstrip("./"))
            for line in io.TextIOWrapper(f, encoding="utf-8"):
                r = json.loads(line)
                yield split, r["id"], r["text"], r["summary"]


def build_xlsum(out, max_test=826):
    rows = []
    for split, rid, text, summary in xlsum_rows():
        if split != "test":
            continue
        rows.append({
            "id": rid,
            "messages": [{
                "role": "user",
                "content": "อ่านข่าวต่อไปนี้แล้วเขียนสรุปสั้นๆ เป็นภาษาไทย\n\n" + text,
            }],
            "references": [summary],
        })
        if len(rows) >= max_test:
            break
    wjsonl(out, rows)


def build_thaiqa(out, split="validation"):
    from datasets import load_dataset

    ds = load_dataset(THAIQA_DS, THAIQA_CONFIG, split=split)
    rows = []
    for i, r in enumerate(ds):
        ans = r["answers"]
        # lighteval parquet: {"answer": [...], "answer_begin_position": [...]}
        # original squad script: [{"answer": str, "answer_begin_position": int}, ...]
        if isinstance(ans, dict):
            answers = list(ans.get("answer", []))
        elif ans and isinstance(ans[0], dict):
            answers = [a["answer"] for a in ans]
        else:
            answers = list(ans)
        if not answers:
            continue
        rows.append({
            "id": str(r.get("question_id", i)),
            "messages": [{
                "role": "user",
                "content": (
                    "อ่านบทความต่อไปนี้ แล้วตอบคำถามด้วยข้อความสั้นๆ ที่อยู่ในบทความ\n\n"
                    f"บทความ: {r['context']}\n\nคำถาม: {r['question']}\n\nคำตอบ:"
                ),
            }],
            "answers": answers,
        })
    wjsonl(out, rows)


def build_scbmt(out, n, direction="en2th"):
    from datasets import load_dataset

    ds = load_dataset(SCBMT_DS, split="test")
    rng = random.Random(SEED)
    idx = list(range(len(ds)))
    rng.shuffle(idx)

    rows = []
    for i in idx:
        if len(rows) >= n:
            break
        r = ds[i]
        src, tgt = (r["en"], r["th"]) if direction == "en2th" else (r["th"], r["en"])
        if direction == "en2th":
            prompt = f"Translate the following English text into Thai.\n\n{src}\n\nTranslation:"
        else:
            prompt = f"แปลข้อความภาษาไทยต่อไปนี้เป็นภาษาอังกฤษ\n\n{src}\n\nTranslation:"
        rows.append({
            "id": str(i),
            "messages": [{"role": "user", "content": prompt}],
            "references": [tgt],
        })
    wjsonl(out, rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sft-n", type=int, default=8000)
    ap.add_argument("--mt-n", type=int, default=1000)
    ap.add_argument("--mt-direction", default="en2th", choices=["en2th", "th2en"])
    ap.add_argument("--qa-split", default="validation", choices=["train", "validation"])
    ap.add_argument("--skip-sft", action="store_true")
    ap.add_argument("--skip-eval", action="store_true")
    args = ap.parse_args()

    if not args.skip_sft:
        build_sft(args.sft_n, os.path.join(DATA, "sft_train.jsonl"))
    if not args.skip_eval:
        build_xlsum(os.path.join(DATA, "eval_xlsum_th.jsonl"))
        build_thaiqa(os.path.join(DATA, f"eval_thaiqa_{args.qa_split}.jsonl"), args.qa_split)
        build_scbmt(os.path.join(DATA, f"eval_scbmt_{args.mt_direction}.jsonl"),
                    args.mt_n, args.mt_direction)


if __name__ == "__main__":
    main()
