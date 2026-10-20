"""CheckpointedNCP: NextConceptTransformer with per-block gradient
checkpointing in _run_stack. CPU SDPA uses the math backend, so every block
materializes [B, H, S, S] attention weights kept alive for backward —
~8x activation blowup on CPU. Checkpointing recomputes them instead.
"""
import torch
import torch.utils.checkpoint as cp

import ncmthai  # noqa: F401
from models.next_concept import NextConceptTransformer


class CheckpointedNCP(NextConceptTransformer):
    def _run_stack(self, prefix_emb, x, prefix_pad_mask=None):
        x = torch.cat([prefix_emb, x], dim=1)

        attn_mask = self.attn_mask_for_masking
        if prefix_pad_mask is not None:
            attn_mask = attn_mask + self._prefix_pad_bias(
                prefix_pad_mask, x.shape[1], attn_mask.dtype, x.device)

        rope = (self.rope_cos, self.rope_sin) if self.use_rope else None
        if self.training:
            for block in self.transformer.blocks:
                x = cp.checkpoint(block, x, attn_mask, rope, None,
                                  use_reentrant=False)
        else:
            for block in self.transformer.blocks:
                x = block(x, attn_mask=attn_mask, rope_cos_sin=rope)
        x = self.transformer.ln_f(x)

        x_target = x[:, self.prefix_len:, :]
        logits_list = []
        if self.predict_level0:
            l0_h = self._level0_slice(x, prefix_pad_mask)
            logits_list.append(self._pad_vocab(self.lm_head_l0(l0_h)))
        offset = 0
        for i, level in enumerate(self.levels[self._lvl_first:]):
            logits_list.append(self._pad_vocab(
                self.lm_heads[i](x_target[:, offset:offset + level, :])))
            offset += level
        return torch.cat(logits_list, dim=1)
