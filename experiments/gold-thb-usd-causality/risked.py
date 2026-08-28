"""Walk-forward backtest with THB signal, volatility sizing, and drawdown stop.

This is research code, not a live trading strategy.

Usage:
    .venv/bin/python risked.py
    VOL_TARGET=0.10 STOP_DD=0.15 .venv/bin/python risked.py
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
VOL_TARGET = float(os.environ.get("VOL_TARGET", "0.10"))
STOP_DD = float(os.environ.get("STOP_DD", "0.15"))
MAX_LEV = float(os.environ.get("MAX_LEV", "1.5"))


def load():
    if not (DATA / "returns.csv").exists():
        print("Run analyze.py first to generate data/returns.csv", file=sys.stderr)
        raise SystemExit(1)
    df = pd.read_csv(DATA / "returns.csv", parse_dates=["date"])
    df = df.sort_values("date").dropna()
    df.set_index("date", inplace=True)
    df["xau_t1"] = df["xau_ret"].shift(-1)
    df = df.dropna()
    ann_vol = df["xau_ret"].expanding(min_periods=21).std().shift(1) * np.sqrt(252)
    # Volatility sizing: target annual vol / realized annual vol, capped at MAX_LEV
    sizing = VOL_TARGET / ann_vol
    sizing = sizing.clip(upper=MAX_LEV)
    df["sizing"] = sizing.fillna(1.0)
    return df


def simulate(df, thresholds, tc=TC):
    """Simulate with a threshold for each row. thresholds is a Series or scalar."""
    if not isinstance(thresholds, pd.Series):
        thresholds = pd.Series(thresholds, index=df.index)
    equity = 1.0
    running_max = 1.0
    prev_pos = 0.0
    records = []
    for i, date in enumerate(df.index):
        threshold = float(thresholds.iloc[i])
        thb = float(df["thb_ret"].iloc[i])
        sizing = float(df["sizing"].iloc[i])
        if thb > threshold:
            signal = -1.0
        elif thb < -threshold:
            signal = 1.0
        else:
            signal = 0.0
        dd = equity / running_max - 1.0
        if dd < -STOP_DD:
            pos = 0.0
        else:
            pos = signal * sizing
        y = float(df["xau_t1"].iloc[i])
        ret = pos * y - tc * abs(pos - prev_pos)
        equity *= np.exp(ret)
        running_max = max(running_max, equity)
        records.append({
            "date": date,
            "position": pos,
            "strategy_ret": ret,
            "equity": equity,
            "buyhold_ret": y,
        })
        prev_pos = pos
    return pd.DataFrame(records).set_index("date")


def search_threshold(train):
    best = {"sharpe": -np.inf, "threshold": 0.0}
    upper = train["thb_ret"].abs().quantile(0.75)
    if upper == 0:
        return 0.0
    for c in np.linspace(0.0, upper, 21):
        result = simulate(train, c, tc=0.0)
        rets = result["strategy_ret"]
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
    months = df.index.to_period("M").unique()

    thresholds = pd.Series(0.0, index=df.index)
    month_records = []
    for month in months:
        month_mask = df.index.to_period("M") == month
        month_dates = df[month_mask]
        if len(month_dates) == 0:
            continue
        start = month_dates.index[0]
        train_end = start - pd.Timedelta(days=1)
        train = df[df.index < train_end].tail(LOOKBACK)

        if len(train) < 126:
            threshold = 0.0
            w = 1.0
        else:
            threshold = search_threshold(train)
            w = 1.0

        thresholds.loc[month_mask] = threshold
        month_records.append({
            "month": str(month),
            "threshold": threshold,
            "n_train": int(len(train)),
        })

    result = simulate(df, thresholds)
    strat_perf = performance(result["strategy_ret"], result["equity"])
    bh = np.exp(result["buyhold_ret"].cumsum())
    bh_perf = performance(result["buyhold_ret"], bh)

    print(f"Risked walk-forward: LOOKBACK={LOOKBACK}, VOL_TARGET={VOL_TARGET}, STOP_DD={STOP_DD}, MAX_LEV={MAX_LEV}, TC={TC*100:.4f}%")
    print(f"Total OOS days: {len(result)}")
    print(f"Date range: {result.index.min().date()} to {result.index.max().date()}")
    print()

    print("=== Risked strategy (THB + vol sizing + stop) ===")
    for k, v in strat_perf.items():
        print(f"  {k}: {v:.4f}")
    print()

    print("=== Buy-and-hold XAU ===")
    for k, v in bh_perf.items():
        print(f"  {k}: {v:.4f}")
    print()

    equity = pd.DataFrame({
        "strategy_ret": result["strategy_ret"],
        "buyhold_ret": result["buyhold_ret"],
        "strategy_equity": result["equity"],
        "buyhold_equity": bh,
        "position": result["position"],
    })
    equity.to_csv(DATA / "risked_equity.csv")

    summary = {
        "lookback_days": LOOKBACK,
        "vol_target": VOL_TARGET,
        "stop_dd": STOP_DD,
        "max_lev": MAX_LEV,
        "tc_per_trade": TC,
        "n_months": len(month_records),
        "n_days": int(len(result)),
        "strategy_metrics": strat_perf,
        "buyhold_metrics": bh_perf,
        "monthly_thresholds": month_records,
        "note": "Risk-managed THB walk-forward. Research only.",
    }
    (DATA / "risked_results.json").write_text(json.dumps(summary, indent=2))
    print("Saved: data/risked_equity.csv, data/risked_results.json")


if __name__ == "__main__":
    main()
