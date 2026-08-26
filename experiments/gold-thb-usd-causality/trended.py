"""Walk-forward backtest using multi-day THB trend and multi-day XAU horizon.

Signal: rolling TREND_WINDOW-day log return of USD/THB.
Target: XAU_HORIZON-day log return of XAU/USD.
Trades are rebalanced every XAU_HORIZON trading days.
Research only, not a live trading strategy.

Usage:
    TREND_WINDOW=5 XAU_HORIZON=5 .venv/bin/python trended.py
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
TREND_WINDOW = int(os.environ.get("TREND_WINDOW", "3"))
XAU_HORIZON = int(os.environ.get("XAU_HORIZON", "1"))
TC = float(os.environ.get("TC", "0.0005"))


def load():
    if not (DATA / "aligned.csv").exists():
        print("Run analyze.py first to generate data/aligned.csv", file=sys.stderr)
        raise SystemExit(1)
    df = pd.read_csv(DATA / "aligned.csv", parse_dates=["date"])
    df = df.sort_values("date").dropna()
    df.set_index("date", inplace=True)

    logdf = np.log(df)
    df["thb_ret"] = logdf["thb"].diff()
    df["xau_ret"] = logdf["xau"].diff()
    df["thb_trend"] = df["thb_ret"].rolling(TREND_WINDOW).sum()
    df["xau_tH"] = logdf["xau"].shift(-XAU_HORIZON) - logdf["xau"]
    df = df.dropna()
    return df


def search_threshold(train):
    best = {"sharpe": -np.inf, "threshold": 0.0}
    upper = train["thb_trend"].abs().quantile(0.75)
    if upper == 0:
        return 0.0
    for c in np.linspace(0.0, upper, 21):
        signal = pd.Series(0, index=train.index, dtype=float)
        signal[train["thb_trend"] > c] = -1.0
        signal[train["thb_trend"] < -c] = 1.0
        rets = signal * train["xau_tH"]
        if rets.std() == 0:
            continue
        sharpe = rets.mean() / rets.std() * np.sqrt(252 / XAU_HORIZON)
        if sharpe > best["sharpe"]:
            best = {"sharpe": sharpe, "threshold": float(c)}
    return best["threshold"]


def performance(rets, eq):
    rets = rets.dropna()
    if len(rets) == 0 or rets.std() == 0:
        return {"sharpe": 0.0, "annual_return": 0.0, "annual_vol": 0.0, "max_dd": 0.0, "win_rate": 0.0}
    # Annualize H-period blocks
    annual_factor = 252 / XAU_HORIZON
    running_max = eq.cummax()
    drawdown = eq / running_max - 1.0
    return {
        "sharpe": float(rets.mean() / rets.std() * np.sqrt(annual_factor)),
        "annual_return": float(rets.mean() * annual_factor),
        "annual_vol": float(rets.std() * np.sqrt(annual_factor)),
        "max_dd": float(drawdown.min()),
        "win_rate": float((rets > 0).sum() / len(rets)),
    }


def main():
    df = load()
    # Rebalance every XAU_HORIZON trading days
    rebalance_dates = df.index[::XAU_HORIZON]
    # Drop the last few where xau_tH is not available
    rebalance_dates = [d for d in rebalance_dates if d in df.index and not pd.isna(df.loc[d, "xau_tH"])]

    records = []
    prev_pos = 0.0
    month_records = []
    for d in rebalance_dates:
        train = df[df.index < d].tail(LOOKBACK)
        if len(train) < 126:
            threshold = 0.0
            pos = 0.0
        else:
            threshold = search_threshold(train)
            trend = df.loc[d, "thb_trend"]
            if trend > threshold:
                pos = -1.0
            elif trend < -threshold:
                pos = 1.0
            else:
                pos = 0.0

        ret = pos * df.loc[d, "xau_tH"] - TC * abs(pos - prev_pos)
        prev_pos = pos

        records.append({
            "date": d,
            "thb_trend": df.loc[d, "thb_trend"],
            "xau_tH": df.loc[d, "xau_tH"],
            "position": pos,
            "strategy_ret": ret,
        })
        month_records.append({
            "rebalance": str(d),
            "threshold": threshold,
            "n_train": int(len(train)),
            "position": pos,
        })

    result = pd.DataFrame(records).set_index("date").sort_index()
    result["equity"] = np.exp(result["strategy_ret"].cumsum())
    result["buyhold_equity"] = np.exp(result["xau_tH"].cumsum())

    strat_perf = performance(result["strategy_ret"], result["equity"])
    bh_perf = performance(result["xau_tH"], result["buyhold_equity"])

    print(f"Trended: TREND_WINDOW={TREND_WINDOW}, XAU_HORIZON={XAU_HORIZON}, LOOKBACK={LOOKBACK}, TC={TC*100:.4f}%")
    print(f"Rebalances: {len(result)}")
    print(f"Date range: {result.index.min().date()} to {result.index.max().date()}")
    print()

    print("=== Multi-day trend strategy ===")
    for k, v in strat_perf.items():
        print(f"  {k}: {v:.4f}")
    print()

    print("=== Buy-and-hold XAU over same H-day blocks ===")
    for k, v in bh_perf.items():
        print(f"  {k}: {v:.4f}")
    print()

    result.to_csv(DATA / "trended_equity.csv")
    summary = {
        "trend_window": TREND_WINDOW,
        "xau_horizon": XAU_HORIZON,
        "lookback_days": LOOKBACK,
        "tc_per_trade": TC,
        "n_rebalances": int(len(result)),
        "strategy_metrics": strat_perf,
        "buyhold_metrics": bh_perf,
        "rebalances": month_records,
        "note": "Multi-day THB trend, H-day XAU horizon, H-day rebalancing. Research only.",
    }
    (DATA / "trended_results.json").write_text(json.dumps(summary, indent=2))
    print("Saved: data/trended_equity.csv, data/trended_results.json")


if __name__ == "__main__":
    main()
