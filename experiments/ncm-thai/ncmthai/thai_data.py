"""Thai corpus prep: stream mC4 'th' (allenai/c4) -> cleaned text file for the
SP trainer and fixed-length id tensors for the VQ-VAE / generator.

Usage:
  python -m ncmthai.thai_data --out-dir data --text-mb 200 --seq-len 128 \
      --sp data/spm_thai.model

Two passes over the downloaded text:
  1) --dump-text writes thai_corpus.txt (used by sp_tokenizer.py --input).
  2) --encode (needs --sp) writes thai_ids.pt {"ids": [N, seq_len]} — docs
     BOS..EOS packed to seq_len, padded with PAD.
"""
import argparse
import os

import torch


def stream_mc4_th(max_chars):
    """Yield Thai text lines from mC4 until max_chars reached."""
    from datasets import load_dataset
    ds = load_dataset("allenai/c4", "th", split="train", streaming=True)
    n = 0
    for ex in ds:
        t = ex["text"].strip()
        if len(t) < 100:
            continue
        yield t
        n += len(t)
        if n >= max_chars:
            return


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default="data")
    ap.add_argument("--text-mb", type=int, default=200)
    ap.add_argument("--seq-len", type=int, default=128)
    ap.add_argument("--sp", default="")
    ap.add_argument("--max-docs", type=int, default=0)
    ap.add_argument("--max-rows", type=int, default=400000)
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)

    corpus = os.path.join(a.out_dir, "thai_corpus.txt")
    if not os.path.exists(corpus):
        cap = a.text_mb * 1024 * 1024
        n_docs = n_chars = 0
        with open(corpus, "w", encoding="utf-8") as f:
            for t in stream_mc4_th(cap):
                # mC4 lines are already single-line documents
                f.write(t.replace("\n", " ") + "\n")
                n_docs += 1
                n_chars += len(t)
                if a.max_docs and n_docs >= a.max_docs:
                    break
        print(f"dumped {n_docs} docs, {n_chars / 1e6:.1f}M chars -> {corpus}")
    else:
        print(f"reusing {corpus}")

    if a.sp:
        from ncmthai.sp_tokenizer import SPTokenizer
        tk = SPTokenizer(a.sp)
        docs = []
        with open(corpus, encoding="utf-8") as f:
            for line in f:
                ids = [tk.bos_token_id] + tk.encode(line.strip()) + \
                    [tk.eos_token_id]
                for i in range(0, len(ids), a.seq_len):
                    chunk = ids[i:i + a.seq_len]
                    if len(chunk) < a.seq_len:
                        chunk += [tk.pad_token_id] * (a.seq_len - len(chunk))
                    docs.append(chunk)
                    if a.max_rows and len(docs) >= a.max_rows:
                        break
                if a.max_rows and len(docs) >= a.max_rows:
                    break
        ids = torch.tensor(docs, dtype=torch.long)
        out = os.path.join(a.out_dir, "thai_ids.pt")
        torch.save({"ids": ids, "prefixes": None}, out)
        print(f"encoded {ids.shape} -> {out}")


if __name__ == "__main__":
    main()
