"""NCM toy-train: reimplemented two-stage trainer for HazyResearch/ncm.

The upstream repo ships all model code but no training loops. This package
implements the missing pieces per arXiv:2610.14162:

  - Stage 1: multiscale residual VQ-VAE tokenizer trainer
    (recon CE + vq_loss with nested dropout; EMA codebook updates live in
    the model's forward under self.training).
  - Stage 2: level-parallel generator trainer with conditioning corruption
    and level-weighted L_NCM.
  - Data: Sudoku generator (validation milestone), mC4/OSCAR Thai prep,
    SentencePiece base-tokenizer wrapper.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
UPSTREAM = os.path.normpath(os.path.join(_HERE, "..", "..", "ncm-upstream"))
if UPSTREAM not in sys.path:
    sys.path.insert(0, UPSTREAM)
