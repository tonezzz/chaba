"""Shared training plumbing: optimizer param groups, LR schedule, checkpointing."""
import math
import os
import time

import torch


def adamw_groups(model, weight_decay):
    decay, no_decay = [], []
    for name, p in model.named_parameters():
        if not p.requires_grad:
            continue
        (no_decay if p.ndim < 2 else decay).append(p)
    return [
        {"params": decay, "weight_decay": weight_decay},
        {"params": no_decay, "weight_decay": 0.0},
    ]


def make_optimizer(model, lr, betas, weight_decay):
    return torch.optim.AdamW(
        adamw_groups(model, weight_decay), lr=lr, betas=betas, eps=1e-8)


def lr_at(step, warmup, total, peak, floor):
    """Linear warmup then cosine decay to floor (paper: peak -> 0.1*peak floor)."""
    if step < warmup:
        return peak * (step + 1) / warmup
    if total <= warmup:
        return floor
    t = (step - warmup) / (total - warmup)
    t = min(max(t, 0.0), 1.0)
    return floor + (peak - floor) * 0.5 * (1.0 + math.cos(math.pi * t))


def set_lr(opt, lr):
    for g in opt.param_groups:
        g["lr"] = lr


def save_ckpt(path, model, step, extra=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = {"model": model.state_dict(), "step": step}
    if extra:
        payload.update(extra)
    torch.save(payload, path)


class Log:
    def __init__(self, tag):
        self.tag = tag
        self.t0 = time.time()
        self.last = self.t0

    def __call__(self, step, msg):
        now = time.time()
        print(f"[{self.tag}] step {step} +{now - self.last:.1f}s "
              f"({now - self.t0:.0f}s total) {msg}", flush=True)
        self.last = now
