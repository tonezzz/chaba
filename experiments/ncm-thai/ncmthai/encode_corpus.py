"""Pre-encode a corpus of pre-tokenizer ids into VQ codes for generator
training. train_generator encodes on the fly (fine for smoke), but real runs
should precompute once.

Usage:
  python -m ncmthai.encode_corpus --config configs/thai-toy.yaml \
      --in data/thai_ids.pt --out data/thai_codes.pt --bs 128
"""
import argparse
import os

import torch
from omegaconf import OmegaConf

import ncmthai  # noqa: F401
from ncmthai.train_generator import load_frozen_vqvae


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--bs", type=int, default=128)
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    a = ap.parse_args()
    cfg = OmegaConf.load(a.config)
    vqvae = load_frozen_vqvae(cfg, a.device)
    data = torch.load(a.inp, weights_only=False)
    ids = data["ids"]
    codes = []
    with torch.no_grad():
        for i in range(0, len(ids), a.bs):
            codes.append(vqvae.encode(ids[i:i + a.bs].to(a.device)).cpu())
            if (i // a.bs) % 20 == 0:
                print(f"{i}/{len(ids)}", flush=True)
    out = {"codes": torch.cat(codes), "prefixes": data.get("prefixes")}
    torch.save(out, a.out)
    print(f"wrote {a.out}: {out['codes'].shape}")


if __name__ == "__main__":
    main()
