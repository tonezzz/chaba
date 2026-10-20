"""Stage 1: train the multiscale residual VQ-VAE tokenizer.

L_tok = recon_CE(x, decoder(z_hat)) + vq_loss, where vq_loss (returned by the
quantizer's forward) already contains the beta-weighted commitment term and the
latent MSE. Nested dropout (fine_drop) and EMA codebook updates happen inside
the quantizer forward while the module is in train mode — matching the paper's
L_tok evaluated at a sampled truncation level.

Usage:
  python -m ncmthai.train_tokenizer --config configs/sudoku-toy.yaml
"""
import argparse
import os

import torch
import torch.nn.functional as F
from omegaconf import OmegaConf

import ncmthai  # noqa: F401  (sys.path hook for upstream)
from models.vqvae import VQVAE
from ncmthai.train_common import make_optimizer, lr_at, set_lr, save_ckpt, Log


def build_vqvae(cfg):
    vcfg = OmegaConf.to_container(cfg.tokenizer.vqvae, resolve=True)
    vcfg["vector_quantizer_config"] = OmegaConf.create(
        vcfg["vector_quantizer_config"])
    return VQVAE(**vcfg)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    ap.add_argument("--data", default="", help="override cfg.data.train")
    ap.add_argument("--updates", type=int, default=0)
    ap.add_argument("--batch", type=int, default=0)
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    cfg = OmegaConf.load(a.config)
    t = cfg.training.tokenizer
    if a.updates:
        t.updates = a.updates
    if a.batch:
        t.batch_size = a.batch
    if a.out:
        cfg.out.dir = a.out
    dev = a.device
    torch.manual_seed(int(getattr(t, "seed", 42)))

    data = torch.load(a.data or cfg.data.train, weights_only=False)
    ids = data["ids"] if isinstance(data, dict) else data  # [N, L] long
    assert ids.shape[1] == cfg.tokenizer.vqvae.context_length
    N = ids.shape[0]

    vqvae = build_vqvae(cfg).to(dev)
    vqvae.train()
    opt = make_optimizer(vqvae, t.peak_lr, tuple(t.betas), t.weight_decay)
    log = Log("tok")
    B = int(t.batch_size)
    amp = bool(getattr(t, "bf16", False)) and dev == "cuda"

    hit_snap = None
    for step in range(int(t.updates)):
        set_lr(opt, lr_at(step, t.warmup, t.updates, t.peak_lr, t.min_lr))
        batch = ids[torch.randint(0, N, (B,))].to(dev, non_blocking=True)
        with torch.autocast("cuda", dtype=torch.bfloat16, enabled=amp):
            logits, vq_loss, lvl_util, glob_util, _ = vqvae(batch)
            recon = F.cross_entropy(
                logits.float().reshape(-1, logits.shape[-1]),
                batch.reshape(-1))
            loss = recon + vq_loss
        opt.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(vqvae.parameters(), t.grad_clip)
        opt.step()

        if step % int(t.log_every) == 0 or step == int(t.updates) - 1:
            hit = [getattr(vqvae.vq, f"codebook_hit_{i}").clone()
                   for i in range(len(vqvae.vq.levels))]
            if hit_snap is not None:
                used = [int(((h - s) > 0).sum()) for h, s in zip(hit, hit_snap)]
                util = ",".join(str(u) for u in used)
            else:
                util = "-"
            hit_snap = hit
            log(step, f"loss={loss.item():.4f} recon={recon.item():.4f} "
                      f"vq={vq_loss.item():.4f} codes/level={util} "
                      f"lr={opt.param_groups[0]['lr']:.2e}")
        if int(t.save_every) > 0 and (step + 1) % int(t.save_every) == 0:
            save_ckpt(os.path.join(cfg.out.dir, "tokenizer.pt"), vqvae, step + 1)

    save_ckpt(os.path.join(cfg.out.dir, "tokenizer.pt"), vqvae, int(t.updates))
    print(f"[tok] done -> {cfg.out.dir}/tokenizer.pt", flush=True)


if __name__ == "__main__":
    main()
