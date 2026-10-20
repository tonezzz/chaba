"""Thai NCM eval vs AR baseline (paper protocol, scaled to toy):

  - held-out token PPL of the AR baseline on real text
  - NCM unconditional samples: Gen-PPL under the AR reference + unigram
    entropy + wall-clock per 128-token sequence (vs AR generate on same box)

Usage:
  python -m ncmthai.eval_thai --config configs/thai-toy.yaml \
      --ckpt runs/thai-toy --ar runs/thai-ar/ar.pt --sp data/spm_thai.model \
      --eval-data data/thai_ids.pt --n-samples 64 --n-eval-docs 500
"""
import argparse
import math
import time
import types
from collections import Counter

import torch
import torch.nn.functional as F
from omegaconf import OmegaConf

import ncmthai  # noqa: F401
import ncmthai.sp_tokenizer  # noqa: F401  registers "spm"
from models.next_concept import NextConceptTransformer
from ncmthai.ar_baseline import ARLM
from ncmthai.sp_tokenizer import SPTokenizer
from ncmthai.train_tokenizer import build_vqvae


def ar_ppl(model, ids, batch=32):
    tot, cnt = 0.0, 0
    with torch.no_grad():
        for i in range(0, len(ids), batch):
            b = ids[i:i + batch]
            x, y = b[:, :-1], b[:, 1:]
            lg = model(x)
            tot += F.cross_entropy(lg.reshape(-1, lg.shape[-1]).float(),
                                   y.reshape(-1), reduction="sum").item()
            cnt += y.numel()
    return math.exp(tot / cnt)


def unigram_entropy(sample_ids, vocab):
    c = Counter()
    n = 0
    for row in sample_ids:
        for t in row:
            c[t] += 1
            n += 1
    return -sum((v / n) * math.log(v / n) for v in c.values())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--ckpt", required=True)
    ap.add_argument("--ar", required=True)
    ap.add_argument("--ar-args", default="",
                    help="embd,layers,heads of the AR checkpoint")
    ap.add_argument("--sp", required=True)
    ap.add_argument("--eval-data", required=True)
    ap.add_argument("--n-eval-docs", type=int, default=500)
    ap.add_argument("--n-samples", type=int, default=64)
    ap.add_argument("--bs", type=int, default=16)
    ap.add_argument("--device", default="cpu")
    a = ap.parse_args()

    cfg = OmegaConf.load(a.config)
    dev = a.device
    tk = SPTokenizer(a.sp)
    embd, layers, heads = (int(v) for v in a.ar_args.split(",")) \
        if a.ar_args else (384, 8, 6)
    ar = ARLM(tk.vocab_size, cfg.tokenizer.vqvae.context_length,
              embd, layers, heads).to(dev)
    ar.load_state_dict(torch.load(a.ar, map_location="cpu",
                                  weights_only=False)["model"])
    ar.eval()

    ids = torch.load(a.eval_data, weights_only=False)["ids"]
    eval_ids = ids[-a.n_eval_docs:].to(dev)
    print(f"AR held-out PPL: {ar_ppl(ar, eval_ids):.2f}", flush=True)

    vqvae = build_vqvae(cfg)
    vqvae.load_state_dict(torch.load(f"{a.ckpt}/{cfg.checkpoints.tokenizer}",
                                   map_location="cpu",
                                   weights_only=False)["model"])
    vqvae.to(dev).eval()
    net = NextConceptTransformer(vqvae_local=vqvae, config=cfg.model).to(dev)
    net.load_state_dict(torch.load(f"{a.ckpt}/{cfg.checkpoints.generator}",
                                   map_location="cpu",
                                   weights_only=False)["model"])
    net.eval()
    P = int(cfg.model.prefix_len)
    eos = int(cfg.data.eos_id)
    gen_cfg = cfg.get("generation", {})

    samples, t_ncm = [], 0.0
    for _ in range(0, a.n_samples, a.bs):
        pids = torch.full((a.bs, P), eos, dtype=torch.long, device=dev)
        t0 = time.time()
        codes = net.generate(None, pids,
                             temperature=float(gen_cfg.get("temperature", 1.0)),
                             top_k=int(gen_cfg.get("top_k", 0)),
                             top_p=float(gen_cfg.get("top_p", 1.0)))
        t_ncm += time.time() - t0
        _, zl = vqvae.vq.idx_to_zhats(codes, return_zlevels=True)
        samples += vqvae.decoder(zl[-1]).argmax(-1).tolist()
    texts = [tk.decode(s, skip_special_tokens=True) for s in samples]
    print(f"NCM gen: {a.bs}x{math.ceil(a.n_samples / a.bs)} seqs in "
          f"{t_ncm:.1f}s -> {t_ncm / a.n_samples * a.bs / a.bs:.3f}s/seq "
          f"(NFE={len(vqvae.vq.levels)})")

    L = cfg.tokenizer.vqvae.context_length
    padded = torch.full((len(texts), L), tk.pad_token_id,
                        dtype=torch.long, device=dev)
    for i, t in enumerate(texts):
        s = torch.tensor([tk.bos_token_id] + tk.encode(t), dtype=torch.long)
        padded[i, :min(len(s), L)] = s[:L].to(dev)
    print(f"NCM sample Gen-PPL (AR ref): {ar_ppl(ar, padded):.2f}")
    print(f"NCM unigram entropy: {unigram_entropy(samples, tk.vocab_size):.3f}")

    t0 = time.time()
    _ = ar.generate(torch.full((a.bs, 1), tk.bos_token_id, dtype=torch.long,
                               device=dev),
                    cfg.tokenizer.vqvae.context_length - 1, temperature=1.0)
    t_ar = time.time() - t0
    print(f"AR gen (same box): {t_ar / a.bs:.3f}s/seq "
          f"(NFE={cfg.tokenizer.vqvae.context_length - 1})")
    print("--- samples ---")
    for t_ in texts[:5]:
        print(t_[:160])


if __name__ == "__main__":
    main()
