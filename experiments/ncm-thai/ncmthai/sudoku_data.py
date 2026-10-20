"""Sudoku data generation matching the released NCM/S-FLM token format.

Solution tensor: 9 rows of 9 digits with '|' (10) between rows -> len 89.
Puzzle tensor: [BOS=11] + same layout with blanks as '_' (0) + [BOS=11] -> 91.

Usage:
  python -m ncmthai.sudoku_data --n 30000 --clues 40 --out data/sudoku_train.pt
"""
import argparse
import random

import torch

BOS, SEP, BLANK = 11, 10, 0


def solve(board):
    """Backtracking solver; returns solved 9x9 list or None."""
    empties = [(r, c) for r in range(9) for c in range(9) if board[r][c] == 0]
    def bt(i):
        if i == len(empties):
            return True
        r, c = empties[i]
        nums = list(range(1, 10))
        random.shuffle(nums)
        for n in nums:
            if all(board[r][j] != n for j in range(9)) and \
               all(board[j][c] != n for j in range(9)) and \
               all(board[r // 3 * 3 + a][c // 3 * 3 + b] != n
                   for a in range(3) for b in range(3)):
                board[r][c] = n
                if bt(i + 1):
                    return True
                board[r][c] = 0
        return False
    return board if bt(0) else None


def random_solution():
    return solve([[0] * 9 for _ in range(9)])


def carve(sol, clues):
    cells = [(r, c) for r in range(9) for c in range(9)]
    keep = set(random.sample(cells, clues))
    return [[sol[r][c] if (r, c) in keep else BLANK for c in range(9)]
            for r in range(9)]


def to_tokens(grid, with_bos):
    out = []
    if with_bos:
        out.append(BOS)
    for r in range(9):
        if r:
            out.append(SEP)
        out.extend(grid[r])
    if with_bos:
        out.append(BOS)
    return out


def make_dataset(n, clues, seed=0):
    random.seed(seed)
    sols, puzzles = [], []
    seen = set()
    while len(sols) < n:
        sol = random_solution()
        flat = tuple(x for row in sol for x in row)
        if flat in seen:
            continue
        seen.add(flat)
        sols.append(to_tokens(sol, with_bos=False))
        puzzles.append(to_tokens(carve(sol, clues), with_bos=True))
    return {"ids": torch.tensor(sols, dtype=torch.long),
            "prefixes": torch.tensor(puzzles, dtype=torch.long)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=30000)
    ap.add_argument("--clues", type=int, default=40,
                    help="40 easy / 35 medium / 30 hard")
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    d = make_dataset(a.n, a.clues, a.seed)
    torch.save(d, a.out)
    print(f"wrote {a.out}: {d['ids'].shape} solutions, {d['prefixes'].shape} puzzles")


if __name__ == "__main__":
    main()
