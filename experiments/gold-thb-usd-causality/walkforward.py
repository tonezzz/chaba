"""Walk-forward backtest of the THB->XAU strategy.

Monthly threshold recalibration using the previous 252 trading days.
This is research code, not a live trading strategy.

Usage:
    .venv/bin/python walkforward.py
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
TC = float(os.environ.get("TC", "0.0005"))


def load():
    if not (DATA / "returns.csv").exists():
        print("Run analyze.py first to generate data/returns.csv", file=sys.stderr)
        raise SystemExit(1)
    df = pd.read_csv(DATA / "returns.csv", parse_dates=["date"])
    df = df.sort_values("date").dropna()
    df.set_index("date", inplace=True)
    df["xau_t1"] = df["xau_ret"].shift(-1)
    return df.dropna()


def daily_returns(signal, y, tc=TC):
    delta = signal.diff().fillna(0).abs()
    return signal * y - tc * delta


def search_threshold(train, signal_col="thb_ret", target_col="xau_t1"):
    best = {"sharpe": -np.inf, "threshold": 0.0}
    upper = train[signal_col].abs().quantile(0.75)
    if upper == 0:
        return 0.0
    for c in np.linspace(0.0, upper, 21):
        signal = pd.Series(0, index=train.index, dtype=float)
        signal[train[signal_col] > c] = -1.0
        signal[train[signal_col] < -c] = 1.0
        rets = daily_returns(signal, train[target_col], tc=0.0)
        if rets.std() == 0:
            continue
        sharpe = rets.mean() / rets.std() * np.sqrt(252)
        if sharpe > best["sharpe"]:
            best = {"sharpe": sharpe, "threshold": float(c)}
    return best["threshold"]


def rule(df, threshold, signal_col="thb_ret"):
    signal = pd.Series(0, index=df.index, dtype=float)
    signal[df[signal_col] > threshold] = -1.0
    signal[df[signal_col] < -threshold] = 1.0
    return signal


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


def main():
    df = load()
    months = df.index.to_period("M").unique()

    all_signals = []
    month_records = []
    for month in months:
        month_dates = df[df.index.to_period("M") == month]
        if len(month_dates) == 0:
            continue
        start = month_dates.index[0]
        train_end = start - pd.Timedelta(days=1)
        train = df[df.index < train_end].tail(LOOKBACK)
        test = month_dates.copy()

        if len(train) < 126:
            # Not enough history, stay flat this month
            threshold = None
            signal = pd.Series(0, index=test.index, dtype=float)
        else:
            threshold = search_threshold(train)
            signal = rule(test, threshold)

        all_signals.append(signal)
        month_records.append({
            "month": str(month),
            "threshold": threshold,
            "n_train": int(len(train)),
            "n_test": int(len(test)),
        })

    full_signal = pd.concat(all_signals).sort_index()
    y = df.loc[full_signal.index, "xau_t1"]
    strat_rets = daily_returns(full_signal, y)
    buyhold_rets = y

    print(f"Walk-forward: {LOOKBACK}-day lookback, monthly recalibration, TC={TC*100:.4f}%")
    print(f"Total OOS days: {len(strat_rets)}")
    print(f"Date range: {strat_rets.index.min().date()} to {strat_rets.index.max().date()}")
    print()

    strat_perf = performance(strat_rets)
    bh_perf = performance(buyhold_rets)

    print("=== Strategy (walk-forward OOS) ===")
    for k, v in strat_perf.items():
        print(f"  {k}: {v:.4f}")
    print()

    print("=== Buy-and-hold XAU (same days) ===")
    for k, v in bh_perf.items():
        print(f"  {k}: {v:.4f}")
    print()

    equity = pd.DataFrame({
        "strategy_ret": strat_rets,
        "buyhold_ret": buyhold_rets,
        "strategy_equity": np.exp(strat_rets.cumsum()),
        "buyhold_equity": np.exp(buyhold_rets.cumsum()),
        "position": full_signal,
    })
    equity.to_csv(DATA / "walkforward_equity.csv")

    summary = {
        "lookback_days": LOOKBACK,
        "tc_per_trade": TC,
        "n_months": len(month_records),
        "n_days": int(len(strat_rets)),
        "strategy_metrics": strat_perf,
        "buyhold_metrics": bh_perf,
        "monthly_thresholds": month_records,
        "note": "Walk-forward, monthly threshold recalibration. Research only, not a live strategy.",
    }
    (DATA / "walkforward_results.json").write_text(json.dumps(summary, indent=2))
    print("Saved: data/walkforward_equity.csv, data/walkforward_results.json")


if __name__ == "__main__":
    main()
