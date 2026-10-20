"""Sudoku eval: generate solutions for held-out puzzles, score exact-match
solved rate + board validity. CPU-friendly mirror of eval_shard's exact metric.

Usage:
  python -m ncmthai.eval_sudoku --config configs/sudoku-toy.yaml \
      --ckpt runs/sudoku-toy --n 200 --bs 64
"""
import argparse
import pickle

import torch
from omegaconf import OmegaConf

import ncmthai  # noqa: F401
from models.next_concept import NextConceptTransformer
from ncmthai.sudoku_data import BOS, SEP
from ncmthai.train_tokenizer import build_vqvae


def rows_of(tokens):
    """tokens: 89 ids (digits 1-9 + seps) -> 9x9 grid (blanks impossible)."""
    rows, cur = [], []
    for t in tokens:
        if t == SEP:
            rows.append(cur)
            cur = []
        else:
            cur.append(t)
    rows.append(cur)
    return rows


def is_solution(grid, puzzle_cells):
    if len(grid) != 9 or any(len(r) != 9 or any(not 1 <= v <= 9 for v in r)
                           for r in grid):
        return False, False
    valid = True
    for i in range(9):
        if len(set(grid[i])) != 9 or len({grid[r][i] for r in range(9)}) != 9:
            valid = False
    for br in range(3):
        for bc in range(3):
            if len({grid[3 * br + a][3 * bc + b] for a in range(3)
                    for b in range(3)}) != 9:
                valid = False
    matches = all(grid[r][c] == puzzle_cells[r][c]
                  for r in range(9) for c in range(9)
                  if puzzle_cells[r][c] != 0)
    return valid, valid and matches


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--ckpt", required=True)
    ap.add_argument("--puzzles", required=True)
    ap.add_argument("--solutions", required=True)
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--bs", type=int, default=64)
    ap.add_argument("--device", default="cpu")
    a = ap.parse_args()

    cfg = OmegaConf.load(a.config)
    dev = a.device
    vqvae = build_vqvae(cfg)
    sd = torch.load(f"{a.ckpt}/{cfg.checkpoints.tokenizer}", map_location="cpu",
                    weights_only=False)
    vqvae.load_state_dict(sd["model"], strict=True)
    vqvae.to(dev).eval()
    net = NextConceptTransformer(vqvae_local=vqvae, config=cfg.model).to(dev)
    sd = torch.load(f"{a.ckpt}/{cfg.checkpoints.generator}", map_location="cpu",
                    weights_only=False)
    net.load_state_dict(sd["model"], strict=True)
    net.eval()

    puzzles = pickle.load(open(a.puzzles, "rb"))[:a.n]
    refs = pickle.load(open(a.solutions, "rb"))[:a.n]
    P = int(cfg.model.prefix_len)

    n_valid = n_solved = n_wellformed = 0
    for s in range(0, len(puzzles), a.bs):
        batch = puzzles[s:s + a.bs]
        pids = torch.tensor([(list(p) + [0] * P)[:P] for p in batch],
                            dtype=torch.long, device=dev)
        codes = net.generate(None, pids, temperature=0.0, top_k=0, top_p=1.0)
        _, zl = vqvae.vq.idx_to_zhats(codes, return_zlevels=True)
        ids = vqvae.decoder(zl[-1]).argmax(-1).tolist()
        for j, gen in enumerate(ids):
            grid = rows_of(gen)
            if len(grid) != 9 or any(len(r) != 9 for r in grid):
                continue
            n_wellformed += 1
            pzl = rows_of(batch[j][1:-1])
            valid, solved = is_solution(grid, pzl)
            n_valid += valid
            n_solved += solved
        print(f"  {min(s + a.bs, len(puzzles))}/{len(puzzles)} "
              f"solved={n_solved} valid={n_valid} wellformed={n_wellformed}",
              flush=True)
    n = len(puzzles)
    print(f"RESULT n={n} wellformed={n_wellformed / n:.3f} "
          f"valid={n_valid / n:.3f} solved={n_solved / n:.3f}")


if __name__ == "__main__":
    main()
