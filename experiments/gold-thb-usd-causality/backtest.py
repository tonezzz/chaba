"""Backtest a simple THB->XAU directional strategy.

This is an in-sample research backtest, not a live trading strategy.
Run after analyze.py has generated data/returns.csv and data/results.json.

Usage:
    .venv/bin/python backtest.py
"""
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent
DATA = ROOT / "data"

# Default per-trade transaction cost (round trip, in log-return terms).
# 5 bps per trade is roughly 0.05%.
TC = float(os.environ.get("TC", "0.0005"))


def load():
    if not (DATA / "returns.csv").exists():
        print("Run analyze.py first to generate data/returns.csv", file=sys.stderr)
        raise SystemExit(1)
    df = pd.read_csv(DATA / "returns.csv", parse_dates=["date"])
    df = df.sort_values("date").dropna()
    df.set_index("date", inplace=True)
    return df


def daily_returns(signal, y, tc=TC):
    """signal is a pandas Series of positions in {-1, 0, +1}. y is the next-day XAU return."""
    delta = signal.diff().fillna(0).abs()
    gross = signal * y
    costs = tc * delta
    return gross - costs


def performance(rets):
    rets = rets.dropna()
    if len(rets) == 0 or rets.std() == 0:
        return {"sharpe": 0.0, "annual_return": 0.0, "annual_vol": 0.0, "max_dd": 0.0, "win_rate": 0.0}
    equity = np.exp(rets.cumsum())
    running_max = equity.cummax()
    drawdown = equity / running_max - 1.0
    return {
        "sharpe": float(rets.mean() / rets.std() * np.sqrt(252)),
        "annual_return": float(rets.mean() * 252),
        "annual_vol": float(rets.std() * np.sqrt(252)),
        "max_dd": float(drawdown.min()),
        "win_rate": float((rets > 0).sum() / len(rets)),
    }


def search_threshold(train, signal_col, target_col):
    best = {"sharpe": -np.inf, "threshold": 0.0}
    for c in np.linspace(0.0, train[signal_col].abs().quantile(0.75), 21):
        signal = pd.Series(0, index=train.index, dtype=float)
        signal[train[signal_col] > c] = -1.0   # stronger USD -> short gold
        signal[train[signal_col] < -c] = 1.0   # weaker USD -> long gold
        y = train[target_col]
        rets = daily_returns(signal, y)
        p = performance(rets)
        if p["sharpe"] > best["sharpe"]:
            best = {"sharpe": p["sharpe"], "threshold": float(c)}
    return best["threshold"]


def rule(df, threshold, signal_col):
    signal = pd.Series(0, index=df.index, dtype=float)
    signal[df[signal_col] > threshold] = -1.0
    signal[df[signal_col] < -threshold] = 1.0
    return signal


def main():
    df = load()
    # target is the next-day XAU return, signal is today's THB return
    df["xau_t1"] = df["xau_ret"].shift(-1)
    df = df.dropna()

    split = pd.Timestamp("2020-01-01")
    train = df[df.index < split].copy()
    test = df[df.index >= split].copy()

    print(f"Train: {len(train)} days ({train.index.min().date()} to {train.index.max().date()})")
    print(f"Test:  {len(test)} days  ({test.index.min().date()} to {test.index.max().date()})")
    print(f"Transaction cost per trade: {TC*100:.4f}%")
    print()

    threshold = search_threshold(train, "thb_ret", "xau_t1")
    print(f"Optimal train threshold: {threshold:.6f}")

    # Train performance
    train_signal = rule(train, threshold, "thb_ret")
    train_strat = daily_returns(train_signal, train["xau_t1"])
    train_buyhold = train["xau_t1"]

    # Test performance
    test_signal = rule(test, threshold, "thb_ret")
    test_strat = daily_returns(test_signal, test["xau_t1"])
    test_buyhold = test["xau_t1"]

    train_metrics = performance(train_strat)
    test_metrics = performance(test_strat)
    test_buyhold_metrics = performance(test_buyhold)

    print("=== Train metrics (in-sample, used for threshold selection) ===")
    for k, v in train_metrics.items():
        print(f"  {k}: {v:.4f}")
    print()

    print("=== Test metrics (out-of-sample) ===")
    for k, v in test_metrics.items():
        print(f"  {k}: {v:.4f}")
    print()

    print("=== Test buy-and-hold gold (next-day returns) ===")
    for k, v in test_buyhold_metrics.items():
        print(f"  {k}: {v:.4f}")
    print()

    # Save equity curves and summary
    equity = pd.DataFrame({
        "strategy_cum_log_ret": test_strat.cumsum(),
        "strategy_equity": np.exp(test_strat.cumsum()),
        "buyhold_cum_log_ret": test_buyhold.cumsum(),
        "buyhold_equity": np.exp(test_buyhold.cumsum()),
        "position": test_signal,
    })
    equity.to_csv(DATA / "backtest_equity.csv")

    summary = {
        "threshold": threshold,
        "tc_per_trade": TC,
        "train_observations": int(len(train)),
        "test_observations": int(len(test)),
        "train_metrics": train_metrics,
        "test_metrics": test_metrics,
        "test_buyhold_metrics": test_buyhold_metrics,
        "note": "In-sample threshold optimization; results may be overfit and should not be used for live trading.",
    }
    (DATA / "backtest_results.json").write_text(json.dumps(summary, indent=2))
    print("Saved: data/backtest_equity.csv, data/backtest_results.json")


if __name__ == "__main__":
    main()
