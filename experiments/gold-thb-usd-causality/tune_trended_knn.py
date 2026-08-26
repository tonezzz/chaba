"""Grid search over WINDOW, K, and WEIGHTED for trended_knn.py.

Usage:
    WINDOWS=3,5 K=20,50 WEIGHTED=0,1 .venv/bin/python tune_trended_knn.py
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent
DATA = ROOT / "data"
VENV_PYTHON = ROOT / ".venv" / "bin" / "python"
TRENDED_KNN = ROOT / "trended_knn.py"

WINDOWS = [int(x) for x in os.environ.get("WINDOWS", "3,5,10").split(",")]
K_VALUES = [int(x) for x in os.environ.get("K", "20,50,100").split(",")]
WEIGHTED_VALUES = [int(x) for x in os.environ.get("WEIGHTED", "0,1").split(",")]


def run_once(window, k, weighted):
    env = os.environ.copy()
    env["WINDOW"] = str(window)
    env["K"] = str(k)
    env["WEIGHTED"] = str(weighted)
    result = subprocess.run(
        [str(VENV_PYTHON), str(TRENDED_KNN)],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        print(f"Error for WINDOW={window}, K={k}, WEIGHTED={weighted}:", file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        return None
    if not (DATA / "trended_knn_results.json").exists():
        return None
    with open(DATA / "trended_knn_results.json") as f:
        data = json.load(f)
    return {
        "window": window,
        "k": k,
        "weighted": bool(weighted),
        "sharpe": data["strategy_metrics"]["sharpe"],
        "annual_return": data["strategy_metrics"]["annual_return"],
        "annual_vol": data["strategy_metrics"]["annual_vol"],
        "max_dd": data["strategy_metrics"]["max_dd"],
        "win_rate": data["strategy_metrics"]["win_rate"],
    }


def main():
    if not TRENDED_KNN.exists():
        print(f"{TRENDED_KNN} not found", file=sys.stderr)
        raise SystemExit(1)

    rows = []
    n_total = len(WINDOWS) * len(K_VALUES) * len(WEIGHTED_VALUES)
    n = 0
    for w in WINDOWS:
        for k in K_VALUES:
            for weighted in WEIGHTED_VALUES:
                n += 1
                print(f"[{n}/{n_total}] WINDOW={w}, K={k}, WEIGHTED={weighted} ...")
                out = run_once(w, k, weighted)
                if out:
                    rows.append(out)
                    print(f"  sharpe={out['sharpe']:.4f}, ann_ret={out['annual_return']:.4f}, max_dd={out['max_dd']:.4f}")

    if not rows:
        print("No results.", file=sys.stderr)
        raise SystemExit(1)

    df = pd.DataFrame(rows).sort_values("sharpe", ascending=False)
    print()
    print("=== Top 10 by Sharpe ===")
    print(df.head(10).to_string(index=False))
    print()

    df.to_csv(DATA / "trended_knn_grid.csv", index=False)
    (DATA / "trended_knn_grid.json").write_text(json.dumps(rows, indent=2))
    print("Saved: data/trended_knn_grid.csv, data/trended_knn_grid.json")


if __name__ == "__main__":
    main()
