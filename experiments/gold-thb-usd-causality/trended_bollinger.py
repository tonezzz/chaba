"""Bollinger Band mean-reversion on XAU returns (research only)."""
import os
import sys
import json
import numpy as np
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).parent
DATA = ROOT / "data"
BB_WINDOW = int(os.environ.get("BB_WINDOW", "20"))
BB_STD = float(os.environ.get("BB_STD", "2.0"))
TC = float(os.environ.get("TC", "0.0005"))


def performance(rets, positions):
    rets = np.asarray(rets)
    positions = np.asarray(positions)
    r = positions * rets
    sr = r.mean() / r.std() * np.sqrt(252) if r.std() != 0 else 0.0
    ann = r.sum() / len(r) * 252
    vol = r.std() * np.sqrt(252)
    cum = np.cumsum(r)
    cummax = np.maximum.accumulate(cum)
    dd = np.min(cum - cummax)
    win = (r > 0).sum() / (r != 0).sum() if (r != 0).sum() > 0 else np.nan
    return {
        "sharpe": float(sr),
        "annual_return": float(ann),
        "annual_vol": float(vol),
        "max_dd": float(dd),
        "win_rate": float(win),
    }


def main():
    if not (DATA / "aligned_silver.csv").exists():
        print("Run prepare_silver.py first", file=sys.stderr)
        raise SystemExit(1)

    df = pd.read_csv(DATA / "aligned_silver.csv", parse_dates=["date"])
    df = df.sort_values("date").dropna()
    df.set_index("date", inplace=True)
    logdf = np.log(df)
    rets = logdf.diff().dropna()
    rets.columns = ["xau_ret", "thb_ret", "xag_ret"]
    rets["xau_t1"] = logdf["xau"].shift(-1) - logdf["xau"]
    rets = rets.dropna()

    xau = rets["xau_ret"]
    mean = xau.rolling(BB_WINDOW).mean()
    std = xau.rolling(BB_WINDOW).std()
    z = (xau - mean) / std
    # fade the move: long when z < -BB_STD, short when z > BB_STD, size 1 otherwise 0
    pos = np.where(z > BB_STD, -1.0, np.where(z < -BB_STD, 1.0, 0.0))
    # position stays for the next day
    pos = pos[:-1]
    y = rets["xau_t1"].values[1:]
    dates = rets.index[1:]
    xau_t = xau.values[1:]

    r = pos * y - TC * np.abs(np.diff(np.concatenate([[0.0], pos])))
    r = r[1:]  # skip first
    equity = np.cumsum(r)
    equity = np.concatenate([[1.0], 1.0 + equity])

    records = []
    prev_pos = 0.0
    running = 1.0
    for d, p, y_ in zip(dates, pos, y):
        ret = p * y_ - TC * abs(p - prev_pos)
        prev_pos = p
        running *= np.exp(ret)
        records.append({
            "date": d.strftime("%Y-%m-%d"),
            "position": float(p),
            "y_pred": 0.0,
            "p_value": 1.0,
            "xau_t1": float(y_),
            "strategy_ret": float(ret),
            "equity": float(running),
        })

    result = pd.DataFrame(records).set_index("date")
    result.index = pd.to_datetime(result.index)
    result.to_csv(DATA / "trended_bollinger_equity.csv")

    strat = performance(result["xau_t1"].values, result["position"].values)
    bh = performance(result["xau_t1"].values, np.ones(len(result)))

    print(f"Bollinger XAU: WINDOW={BB_WINDOW}, BB_STD={BB_STD}, TC={TC*100:.4f}%")
    print(f"Total OOS days: {len(result)}")
    for k, v in strat.items():
        print(f"  {k}: {v:.4f}")

    summary = {
        "config": {
            "bb_window": BB_WINDOW,
            "bb_std": BB_STD,
            "tc_per_trade": TC,
        },
        "n_days": int(len(result)),
        "strategy_metrics": strat,
        "buyhold_metrics": bh,
        "note": "Bollinger Band mean-reversion on XAU log returns. Research only.",
    }
    (DATA / "trended_bollinger_results.json").write_text(json.dumps(summary, indent=2))
    print("Saved: data/trended_bollinger_equity.csv, data/trended_bollinger_results.json")


if __name__ == "__main__":
    main()
