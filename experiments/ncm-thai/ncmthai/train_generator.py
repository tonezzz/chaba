"""Stage 2: train the NCM transformer on frozen tokenizer codes.

Per paper Algorithm 1: encode x -> clean target codes r_1:K; corrupt a fraction
of conditioning codes per level (shifted linear decreasing rates, mean ~0.5);
build the corrupted cumulative reconstruction inputs via vq.idx_to_ncm_input;
one forward predicts all levels; L_NCM = level-weighted CE with
w_k ∝ ell_k^(-alpha) normalized over positions.

Level-0 codes are not predicted by the generator (predict_level0=false,
query_level0=false in the unconditional recipe); at eval they are sampled from
the empirical unigram, which we accumulate from training batches and store in
the checkpoint under 'inference.level0_unigram' (the format eval_shard.py
expects).

Usage:
  python -m ncmthai.train_generator --config configs/sudoku-toy.yaml
"""
import argparse
import os

import torch
import torch.nn.functional as F
from omegaconf import OmegaConf

import ncmthai  # noqa: F401
from models.next_concept import NextConceptTransformer
from ncmthai.model_wrap import CheckpointedNCP
from ncmthai.corrupt import level_rates, corrupt_codes, level_weights
from ncmthai.train_common import make_optimizer, lr_at, set_lr, save_ckpt, Log
from ncmthai.train_tokenizer import build_vqvae


def load_frozen_vqvae(cfg, dev):
    vqvae = build_vqvae(cfg)
    sd = torch.load(os.path.join(cfg.out.dir, cfg.checkpoints.tokenizer),
                    map_location="cpu", weights_only=False)
    vqvae.load_state_dict(sd["model"], strict=True)
    vqvae.to(dev).eval()
    for p in vqvae.parameters():
        p.requires_grad_(False)
    return vqvae


def ncm_loss(logits, targets, target_levels, alpha):
    """logits: [B, T, Vmax] concatenated per-level heads (padded vocab);
    targets: [B, T] codes; target_levels: which levels the heads cover.
    Returns weighted L_NCM (w_k ∝ ell_k^-alpha over positions)."""
    s = level_weights(target_levels, alpha)
    total = logits.new_zeros(())
    off = 0
    for ell, w in zip(target_levels, s):
        lg = logits[:, off:off + ell, :].float()
        ce = F.cross_entropy(lg.reshape(-1, lg.shape[-1]),
                             targets[:, off:off + ell].reshape(-1),
                             reduction="sum")
        total = total + w * ce
        off += ell
    return total / targets.shape[0]


def prefix_embeddings(model, vqvae, prefix_ids):
    """Prefix z for the generator input (raw token prefix path)."""
    return vqvae.encoder.wte(prefix_ids)[:, : model.prefix_len, :]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    ap.add_argument("--data", default="")
    ap.add_argument("--updates", type=int, default=0)
    ap.add_argument("--batch", type=int, default=0)
    ap.add_argument("--out", default="")
    ap.add_argument("--resume", action="store_true")
    a = ap.parse_args()
    cfg = OmegaConf.load(a.config)
    t = cfg.training.generator
    if a.updates:
        t.updates = a.updates
    if a.batch:
        t.batch_size = a.batch
    if a.out:
        cfg.out.dir = a.out
    dev = a.device
    torch.manual_seed(int(getattr(t, "seed", 42)))

    data = torch.load(a.data or cfg.data.train, weights_only=False)
    ids = data["ids"]                      # [N, L_ctx] pre-tokenizer ids
    prefixes = data.get("prefixes")        # [N, P] or None (unconditional)
    N = ids.shape[0]

    vqvae = load_frozen_vqvae(cfg, dev)
    cls = CheckpointedNCP if bool(getattr(t, "grad_ckpt", dev == "cpu")) \
        else NextConceptTransformer
    model = cls(vqvae_local=vqvae, config=cfg.model).to(dev)
    model.train()
    opt = make_optimizer(model, t.peak_lr, tuple(t.betas), t.weight_decay)
    start_step = 0
    l0_counts = torch.zeros(
        cfg.tokenizer.vqvae.vqvae_vocab_size[0], dtype=torch.long)
    ckpt_path = os.path.join(cfg.out.dir, "generator.pt")
    if a.resume and os.path.exists(ckpt_path):
        sd = torch.load(ckpt_path, map_location="cpu", weights_only=False)
        model.load_state_dict(sd["model"])
        if sd.get("opt"):
            opt.load_state_dict(sd["opt"])
        if sd.get("l0_counts") is not None:
            l0_counts = sd["l0_counts"].long()
        start_step = int(sd.get("step", 0))
        print(f"[gen] resumed at step {start_step}", flush=True)
    log = Log("gen")
    B = int(t.batch_size)
    amp = bool(getattr(t, "bf16", False)) and dev == "cuda"

    vq = vqvae.vq
    levels = list(vq.levels)
    l0 = levels[0]
    ql0 = bool(getattr(cfg.model, "query_level0", False))
    pl0 = bool(getattr(cfg.model, "predict_level0", False))
    if getattr(model, "l0_ar", False):
        raise NotImplementedError("l0_autoregressive training not implemented")
    # Heads cover levels[1:] normally; with query_level0 or predict_level0 the
    # level-0 codes are also predicted, so targets/heads span all levels.
    target_levels = levels if (ql0 or pl0) else levels[1:]
    rates = level_rates(len(levels), float(t.corruption_mean),
                        str(getattr(t, "corruption_schedule", "shifted_linear")))
    alpha = float(getattr(t, "loss_alpha", 0.0))
    pad_id = int(getattr(cfg.model, "prefix_pad_token_id", -1))
    uncond = prefixes is None
    # prefix_dropout: share of conditional samples trained on the null
    # (PAD) prefix — enables CFG at generation for conditional tasks.
    pfx_drop = float(getattr(t, "prefix_dropout", 0.0))

    print(f"[gen] levels={levels} l0={l0} rates={[round(r,2) for r in rates]} "
          f"alpha={alpha} uncond={uncond}", flush=True)

    for step in range(start_step, int(t.updates)):
        set_lr(opt, lr_at(step, t.warmup, t.updates, t.peak_lr, t.min_lr))
        sel = torch.randint(0, N, (B,))
        batch = ids[sel].to(dev)
        if uncond:
            pids = torch.full((B, model.prefix_len), pad_id,
                              dtype=torch.long, device=dev)
            pids[:, 0] = int(cfg.data.eos_id)
            pmask = None
        else:
            pids = prefixes[sel].to(dev)
            if pfx_drop > 0.0 and pad_id >= 0:
                drop = torch.rand(B, device=dev) < pfx_drop
                pids = pids.clone()
                pids[drop] = pad_id
                pids[drop, 0] = int(cfg.data.eos_id)
            pmask = (pids == pad_id) if pad_id >= 0 else None

        with torch.no_grad():
            idx = vqvae.encode(batch)                       # clean codes
            r_tilde = corrupt_codes(idx, levels, vq.vqvae_vocab_sizes, rates)
            ncm_in = vq.idx_to_ncm_input(r_tilde)           # [B, L-l0, D]
            if ql0:
                # level-0 learned queries occupy the first target block.
                ncm_in = torch.cat(
                    [model.build_l0_query_input(B, dtype=ncm_in.dtype),
                     ncm_in], dim=1)
            targets = idx if (ql0 or pl0) else idx[:, l0:]
            l0_counts += torch.bincount(
                idx[:, :l0].reshape(-1).cpu(), minlength=l0_counts.numel())
            x = torch.cat([prefix_embeddings(model, vqvae, pids), ncm_in], dim=1)

        with torch.autocast("cuda", dtype=torch.bfloat16, enabled=amp):
            logits = model(x, prefix_pad_mask=pmask)
            loss = ncm_loss(logits, targets, target_levels, alpha)
        opt.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), t.grad_clip)
        opt.step()

        if step % int(t.log_every) == 0 or step == int(t.updates) - 1:
            with torch.no_grad():
                acc = (logits.argmax(-1) == targets).float().mean().item()
            log(step, f"loss={loss.item():.4f} acc={acc:.3f} "
                      f"lr={opt.param_groups[0]['lr']:.2e}")
        if int(t.save_every) > 0 and (step + 1) % int(t.save_every) == 0:
            save_ckpt(ckpt_path, model, step + 1,
                      {"inference": {"level0_unigram":
                                     (l0_counts / l0_counts.sum()).float()},
                       "opt": opt.state_dict(), "l0_counts": l0_counts})

    save_ckpt(ckpt_path, model, int(t.updates),
              {"inference": {"level0_unigram":
                             (l0_counts / l0_counts.sum()).float()},
               "opt": opt.state_dict(), "l0_counts": l0_counts})
    print(f"[gen] done -> {cfg.out.dir}/generator.pt", flush=True)


if __name__ == "__main__":
    main()
