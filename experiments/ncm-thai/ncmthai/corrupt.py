"""Conditioning corruption for NCM generator training (paper Sec. 3.4 / App. F.3).

During training a fraction of the conditioning codes r~_k are replaced by codes
sampled uniformly from the same level's codebook; targets stay clean. Rates are
per-level on a "shifted linear decreasing" schedule with a configurable mean
(the paper's main recipe uses mean 0.50).
"""
import torch


def level_rates(n_levels: int, mean: float, schedule: str = "shifted_linear"):
    """Per-level corruption rates, indexed by the conditioning level k.

    shifted_linear: linspace(1, 0) across levels, shifted so the mean hits
    `mean`. mean=0.5 -> [1.0, ..., 0.0]; the natural reading of the paper's
    "shifted linear decreasing schedule" (App. F.3).
    """
    if n_levels < 2:
        return [0.0] * n_levels
    if schedule == "none" or mean <= 0.0:
        return [0.0] * n_levels
    if schedule == "uniform":
        return [float(mean)] * n_levels
    if schedule != "shifted_linear":
        raise ValueError(f"unknown corruption schedule {schedule}")
    base = [1.0 - k / (n_levels - 1) for k in range(n_levels)]  # mean 0.5
    shift = 2.0 * (mean - 0.5)
    return [min(1.0, max(0.0, r + shift)) for r in base]


def corrupt_codes(idx: torch.Tensor, levels, vocab_sizes, rates, generator=None):
    """Replace conditioning codes with uniform draws from the same level's codebook.

    idx: [B, sum(levels)] clean codes. Returns corrupted copy; idx unchanged.
    Level k's codes are corrupted at rates[k] (last level's rate is unused by the
    model but kept for completeness).
    """
    out = idx.clone()
    off = 0
    for k, (ell, v) in enumerate(zip(levels, vocab_sizes)):
        r = rates[k]
        if r > 0.0:
            mask = torch.rand(out[:, off:off + ell].shape, device=idx.device,
                              generator=generator) < r
            rand = torch.randint(0, v, out[:, off:off + ell].shape,
                                 device=idx.device, generator=generator)
            out[:, off:off + ell] = torch.where(mask, rand, out[:, off:off + ell])
        off += ell
    return out


def level_weights(levels, alpha: float):
    """L_NCM per-position weights s_k = w_k = ell_k^-alpha / sum_j ell_j^(1-alpha).

    alpha=0 -> every code position weighted 1/N (plain mean CE).
    alpha=1 -> every level equally weighted.
    """
    denom = sum(ell ** (1.0 - alpha) for ell in levels)
    return [ell ** (-alpha) / denom for ell in levels]
