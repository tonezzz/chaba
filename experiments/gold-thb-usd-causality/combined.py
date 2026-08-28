"""Walk-forward backtest with combined THB + USD/EUR signal.

Optimizes the THB weight and threshold monthly on the previous 252 trading days.
This is research code, not a live trading strategy.

Usage:
    .venv/bin/python combined.py
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


def search_params(train, target_col="xau_t1"):
    best = {"sharpe": -np.inf, "w": 1.0, "threshold": 0.0}
    upper = max(train["thb_ret"].abs().quantile(0.75), train["usd_ret"].abs().quantile(0.75))
    if upper == 0:
        return 1.0, 0.0
    for w in [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]:
        composite = w * train["thb_ret"] + (1 - w) * train["usd_ret"]
        for c in np.linspace(0.0, upper, 21):
            signal = pd.Series(0, index=train.index, dtype=float)
            signal[composite > c] = -1.0
            signal[composite < -c] = 1.0
            rets = daily_returns(signal, train[target_col], tc=0.0)
            if rets.std() == 0:
                continue
            sharpe = rets.mean() / rets.std() * np.sqrt(252)
            if sharpe > best["sharpe"]:
                best = {"sharpe": sharpe, "w": float(w), "threshold": float(c)}
    return best["w"], best["threshold"]


def rule(df, w, threshold):
    composite = w * df["thb_ret"] + (1 - w) * df["usd_ret"]
    signal = pd.Series(0, index=df.index, dtype=float)
    signal[composite > threshold] = -1.0
    signal[composite < -threshold] = 1.0
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
            w, threshold = 1.0, 0.0
            signal = pd.Series(0, index=test.index, dtype=float)
        else:
            w, threshold = search_params(train)
            signal = rule(test, w, threshold)

        all_signals.append(signal)
        month_records.append({
            "month": str(month),
            "w_thb": w,
            "threshold": threshold,
            "n_train": int(len(train)),
            "n_test": int(len(test)),
        })

    full_signal = pd.concat(all_signals).sort_index()
    y = df.loc[full_signal.index, "xau_t1"]
    strat_rets = daily_returns(full_signal, y)
    buyhold_rets = y

    print(f"Combined walk-forward: {LOOKBACK}-day lookback, monthly recalibration, TC={TC*100:.4f}%")
    print(f"Total OOS days: {len(strat_rets)}")
    print(f"Date range: {strat_rets.index.min().date()} to {strat_rets.index.max().date()}")
    print()

    strat_perf = performance(strat_rets)
    bh_perf = performance(buyhold_rets)

    print("=== Combined strategy (THB + USD/EUR, walk-forward OOS) ===")
    for k, v in strat_perf.items():
        print(f"  {k}: {v:.4f}")
    print()

    print("=== Buy-and-hold XAU (same days) ===")
    for k, v in bh_perf.items():
        print(f"  {k}: {v:.4f}")
    print()

    avg_w = np.mean([r["w_thb"] for r in month_records if r["w_thb"] is not None])
    print(f"Average THB weight: {avg_w:.3f}")
    print()

    equity = pd.DataFrame({
        "strategy_ret": strat_rets,
        "buyhold_ret": buyhold_rets,
        "strategy_equity": np.exp(strat_rets.cumsum()),
        "buyhold_equity": np.exp(buyhold_rets.cumsum()),
        "position": full_signal,
    })
    equity.to_csv(DATA / "combined_equity.csv")

    summary = {
        "lookback_days": LOOKBACK,
        "tc_per_trade": TC,
        "n_months": len(month_records),
        "n_days": int(len(strat_rets)),
        "avg_w_thb": float(avg_w),
        "strategy_metrics": strat_perf,
        "buyhold_metrics": bh_perf,
        "monthly_params": month_records,
        "note": "Combined THB+USD/EUR walk-forward. Research only, not a live strategy.",
    }
    (DATA / "combined_results.json").write_text(json.dumps(summary, indent=2))
    print("Saved: data/combined_equity.csv, data/combined_results.json")


if __name__ == "__main__":
    main()
