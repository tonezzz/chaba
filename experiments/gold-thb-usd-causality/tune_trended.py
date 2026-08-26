"""Grid search over TREND_WINDOW and XAU_HORIZON for trended.py.

Runs trended.py for each parameter combination, records metrics, and
prints the best by Sharpe.

Usage:
    .venv/bin/python tune_trended.py
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
TRENDED = ROOT / "trended.py"

TREND_WINDOWS = [int(x) for x in os.environ.get("TREND_WINDOWS", "1,2,3,5,10").split(",")]
XAU_HORIZONS = [int(x) for x in os.environ.get("XAU_HORIZONS", "1,3,5").split(",")]


def run_once(tw, h):
    env = os.environ.copy()
    env["TREND_WINDOW"] = str(tw)
    env["XAU_HORIZON"] = str(h)
    result = subprocess.run(
        [str(VENV_PYTHON), str(TRENDED)],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        print(f"Error for TREND_WINDOW={tw}, XAU_HORIZON={h}:", file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        return None
    if not (DATA / "trended_results.json").exists():
        return None
    with open(DATA / "trended_results.json") as f:
        data = json.load(f)
    return {
        "trend_window": tw,
        "xau_horizon": h,
        "sharpe": data["strategy_metrics"]["sharpe"],
        "annual_return": data["strategy_metrics"]["annual_return"],
        "annual_vol": data["strategy_metrics"]["annual_vol"],
        "max_dd": data["strategy_metrics"]["max_dd"],
        "win_rate": data["strategy_metrics"]["win_rate"],
    }


def main():
    if not TRENDED.exists():
        print(f"{TRENDED} not found", file=sys.stderr)
        raise SystemExit(1)

    rows = []
    n_total = len(TREND_WINDOWS) * len(XAU_HORIZONS)
    n = 0
    for tw in TREND_WINDOWS:
        for h in XAU_HORIZONS:
            n += 1
            print(f"[{n}/{n_total}] TREND_WINDOW={tw}, XAU_HORIZON={h} ...")
            out = run_once(tw, h)
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

    df.to_csv(DATA / "trended_grid.csv", index=False)
    (DATA / "trended_grid.json").write_text(json.dumps(rows, indent=2))
    print("Saved: data/trended_grid.csv, data/trended_grid.json")


if __name__ == "__main__":
    main()
