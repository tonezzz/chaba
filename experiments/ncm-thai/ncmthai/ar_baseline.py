"""Small AR transformer baseline trained on the same data as the Thai NCM —
the "quality vs small AR baseline" comparison the card asks for, and doubles
as the reference model for Gen-PPL scoring of NCM samples.

Arch reuses upstream models/common.py Block (RoPE, qk-norm, causal SDPA).

Usage:
  python -m ncmthai.ar_baseline --data data/thai_ids.pt --vocab 8192 \
      --ctx 128 --embd 384 --layers 8 --heads 6 --updates 2000 \
      --batch 64 --out runs/thai-ar/ar.pt
"""
import argparse
import os
import types

import torch
import torch.nn as nn
import torch.nn.functional as F

import ncmthai  # noqa: F401
from models.common import Block, LayerNorm, precompute_rope_cos_sin
from ncmthai.train_common import make_optimizer, lr_at, set_lr, save_ckpt, Log


class ARLM(nn.Module):
    def __init__(self, vocab, ctx, embd, layers, heads, dropout=0.1):
        super().__init__()
        cfg = types.SimpleNamespace(n_embd=embd, n_head=heads, bias=True,
                                    dropout=dropout, use_qk_norm=True,
                                    attn_window=0, use_flex_attention=False)
        self.wte = nn.Embedding(vocab, embd)
        self.blocks = nn.ModuleList([Block(cfg) for _ in range(layers)])
        self.ln_f = LayerNorm(embd, bias=True)
        self.head = nn.Linear(embd, vocab, bias=False)
        self.head.weight = self.wte.weight
        hd = embd // heads
        pos = torch.arange(ctx)
        self.register_buffer("rc", precompute_rope_cos_sin(pos, hd, 10000)[0],
                             persistent=False)
        self.register_buffer("rs", precompute_rope_cos_sin(pos, hd, 10000)[1],
                             persistent=False)

    def forward(self, ids):
        x = self.wte(ids)
        rope = (self.rc, self.rs)
        for b in self.blocks:
            x = b(x, attn_mask=None, rope_cos_sin=rope)  # causal
        return self.head(self.ln_f(x))

    @torch.no_grad()
    def generate(self, ids, n_new, temperature=1.0, top_k=0):
        for _ in range(n_new):
            logits = self.forward(ids[:, -self.rc.shape[0]:])[:, -1]
            if temperature == 0:
                nxt = logits.argmax(-1, keepdim=True)
            else:
                lg = logits / temperature
                if top_k:
                    kth = torch.topk(lg, top_k).values[:, -1, None]
                    lg = lg.masked_fill(lg < kth, -torch.inf)
                nxt = torch.multinomial(F.softmax(lg, -1), 1)
            ids = torch.cat([ids, nxt], 1)
        return ids


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--vocab", type=int, required=True)
    ap.add_argument("--ctx", type=int, default=128)
    ap.add_argument("--embd", type=int, default=384)
    ap.add_argument("--layers", type=int, default=8)
    ap.add_argument("--heads", type=int, default=6)
    ap.add_argument("--dropout", type=float, default=0.1)
    ap.add_argument("--updates", type=int, default=2000)
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--peak-lr", type=float, default=3e-4)
    ap.add_argument("--min-lr", type=float, default=3e-5)
    ap.add_argument("--warmup", type=int, default=100)
    ap.add_argument("--wd", type=float, default=0.1)
    ap.add_argument("--log-every", type=int, default=100)
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    torch.manual_seed(42)
    dev = a.device
    ids = torch.load(a.data, weights_only=False)["ids"]
    N = ids.shape[0]
    model = ARLM(a.vocab, a.ctx, a.embd, a.layers, a.heads, a.dropout).to(dev)
    print(f"AR baseline: {sum(p.numel() for p in model.parameters()) / 1e6:.2f}M")
    opt = make_optimizer(model, a.peak_lr, (0.9, 0.95), a.wd)
    log = Log("ar")

    for step in range(a.updates):
        set_lr(opt, lr_at(step, a.warmup, a.updates, a.peak_lr, a.min_lr))
        batch = ids[torch.randint(0, N, (a.batch,))].to(dev)
        x, y = batch[:, :-1], batch[:, 1:]
        logits = model(x)
        loss = F.cross_entropy(logits.reshape(-1, logits.shape[-1]).float(),
                               y.reshape(-1))
        opt.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        opt.step()
        if step % a.log_every == 0 or step == a.updates - 1:
            log(step, f"loss={loss.item():.4f} ppl={loss.exp().item():.1f} "
                      f"lr={opt.param_groups[0]['lr']:.2e}")

    save_ckpt(a.out, model, a.updates)
    print(f"[ar] done -> {a.out}")


if __name__ == "__main__":
    main()
