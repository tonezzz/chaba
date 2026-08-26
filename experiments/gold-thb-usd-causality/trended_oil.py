"""Walk-forward 2-day oil (WTI) trend baseline for XAU.

Signal: rolling 2-day log return of WTI. Trade the sign when it exceeds a
threshold. Research only.

Usage:
    TREND_WINDOW=2 .venv/bin/python trended_oil.py
"""
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent
DATA = ROOT / "data"
LOOKBACK = int(os.environ.get("LOOKBACK", "252"))
TREND_WINDOW = int(os.environ.get("TREND_WINDOW", "2"))
TC = float(os.environ.get("TC", "0.0005"))


def load():
    if not (DATA / "aligned_oil.csv").exists():
        print("Run prepare_oil.py first to generate data/aligned_oil.csv", file=sys.stderr)
        raise SystemExit(1)
    df = pd.read_csv(DATA / "aligned_oil.csv", parse_dates=["date"])
    df = df.sort_values("date").dropna()
    df.set_index("date", inplace=True)
    logdf = np.log(df)
    col = os.environ.get("OIL_COL", "wti")
    df["oil_ret"] = logdf[col].diff()
    df["xau_t1"] = logdf["xau"].shift(-1) - logdf["xau"]
    df["oil_trend"] = df["oil_ret"].rolling(TREND_WINDOW).sum()
    return df.dropna()


def search_threshold(train):
    best = {"sharpe": -np.inf, "threshold": 0.0}
    upper = train["oil_trend"].abs().quantile(0.75)
    if upper == 0:
        return 0.0
    for c in np.linspace(0.0, upper, 21):
        # Oil and XAU are often positively correlated
        signal = pd.Series(0, index=train.index, dtype=float)
        signal[train["oil_trend"] > c] = 1.0
        signal[train["oil_trend"] < -c] = -1.0
        rets = signal * train["xau_t1"]
        if rets.std() == 0:
            continue
        sharpe = rets.mean() / rets.std() * np.sqrt(252)
        if sharpe > best["sharpe"]:
            best = {"sharpe": sharpe, "threshold": float(c)}
    return best["threshold"]


def performance(rets, eq):
    rets = rets.dropna()
    if len(rets) == 0 or rets.std() == 0:
        return {"sharpe": 0.0, "annual_return": 0.0, "annual_vol": 0.0, "max_dd": 0.0, "win_rate": 0.0}
    running_max = eq.cummax()
    drawdown = eq / running_max - 1.0
    return {
        "sharpe": float(rets.mean() / rets.std() * np.sqrt(252)),
        "annual_return": float(rets.mean() * 252),
        "annual_vol": float(rets.std() * np.sqrt(252)),
        "max_dd": float(drawdown.min()),
        "win_rate": float((rets > 0).sum() / len(rets)),
    }


def main():
    df = load()
    month_map = df.index.to_period("M")
    months = df.index.to_period("M").unique()

    records = []
    prev_pos = 0.0
    month_records = []
    for d in df.index:
        month = month_map[df.index.get_loc(d)]
        if d == months[0] and len(df[df.index < d]) < 126:
            pos = 0.0
            threshold = 0.0
        else:
            train = df[df.index < d].tail(LOOKBACK)
            threshold = search_threshold(train) if len(train) >= 63 else 0.0
            trend = df.loc[d, "oil_trend"]
            if not pd.isna(trend) and trend > threshold:
                pos = 1.0
            elif not pd.isna(trend) and trend < -threshold:
                pos = -1.0
            else:
                pos = 0.0
        ret = pos * df.loc[d, "xau_t1"] - TC * abs(pos - prev_pos)
        prev_pos = pos
        records.append({
            "date": d,
            "oil_trend": df.loc[d, "oil_trend"],
            "xau_t1": df.loc[d, "xau_t1"],
            "position": pos,
            "strategy_ret": ret,
        })

    result = pd.DataFrame(records).set_index("date").sort_index()
    result["equity"] = np.exp(result["strategy_ret"].cumsum())
    result["buyhold_equity"] = np.exp(result["xau_t1"].cumsum())

    strat_perf = performance(result["strategy_ret"], result["equity"])
    bh_perf = performance(result["xau_t1"], result["buyhold_equity"])

    print(f"Oil trend: TREND_WINDOW={TREND_WINDOW}, LOOKBACK={LOOKBACK}, TC={TC*100:.4f}%")
    print(f"Total OOS days: {len(result)}")
    print(f"Date range: {result.index.min().date()} to {result.index.max().date()}")
    print()

    print("=== 2-day oil trend (walk-forward OOS) ===")
    for k, v in strat_perf.items():
        print(f"  {k}: {v:.4f}")
    print()

    print("=== Buy-and-hold XAU (same days) ===")
    for k, v in bh_perf.items():
        print(f"  {k}: {v:.4f}")
    print()

    result.to_csv(DATA / "trended_oil_equity.csv")
    summary = {
        "trend_window": TREND_WINDOW,
        "lookback_days": LOOKBACK,
        "tc_per_trade": TC,
        "n_days": int(len(result)),
        "strategy_metrics": strat_perf,
        "buyhold_metrics": bh_perf,
        "note": "2-day WTI oil trend signal for XAU. Research only.",
    }
    (DATA / "trended_oil_results.json").write_text(json.dumps(summary, indent=2))
    print("Saved: data/trended_oil_equity.csv, data/trended_oil_results.json")


if __name__ == "__main__":
    main()
