"""Walk-forward graph/network edge filter strategy.

For each month, estimate the directed THB -> XAU Granger-causality edge on the
previous 252 days. If the edge is statistically significant (p < P_THRESHOLD),
trade the sign of the recent THB trend; otherwise stay flat. This makes the
lead-lag edge itself a regime filter.

Research only, not a live trading strategy.

Usage:
    TREND_WINDOW=2 P_THRESHOLD=0.05 .venv/bin/python trended_graph.py
"""
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import grangercausalitytests

ROOT = Path(__file__).parent
DATA = ROOT / "data"
LOOKBACK = int(os.environ.get("LOOKBACK", "252"))
TREND_WINDOW = int(os.environ.get("TREND_WINDOW", "2"))
P_THRESHOLD = float(os.environ.get("P_THRESHOLD", "0.05"))
MAX_LAG = int(os.environ.get("MAX_LAG", "5"))
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
    df["xau_t1"] = logdf["xau"].shift(-1) - logdf["xau"]
    return df.dropna()


def granger_p(data, maxlag=MAX_LAG):
    try:
        tests = grangercausalitytests(data, maxlag=maxlag, verbose=False)
        pvals = [tests[lag][0]["ssr_ftest"][1] for lag in tests]
        return float(min(pvals))
    except Exception:
        return 1.0


def search_threshold(thb_trend, xau_t1):
    best = {"sharpe": -np.inf, "threshold": 0.0}
    upper = np.percentile(np.abs(thb_trend), 90)
    for c in np.linspace(0.0, upper, 21):
        signal = np.where(thb_trend > c, -1.0, np.where(thb_trend < -c, 1.0, 0.0))
        rets = signal * xau_t1
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
    equity = 1.0
    month_records = []

    for month in months:
        month_mask = month_map == month
        month_dates = df.index[month_mask]
        if len(month_dates) == 0:
            continue
        start = month_dates[0]

        train = df[df.index < start].tail(LOOKBACK)
        if len(train) < max(TREND_WINDOW, MAX_LAG) + 63:
            for d in month_dates:
                records.append({
                    "date": d,
                    "position": 0.0,
                    "thb_trend": df.loc[d, "thb_trend"],
                    "p_value": 1.0,
                    "y_pred": 0.0,
                    "xau_t1": df.loc[d, "xau_t1"],
                    "strategy_ret": 0.0,
                    "equity": equity,
                })
            continue

        data = train[["xau_ret", "thb_ret"]].dropna().values
        p_value = granger_p(data)
        edge_active = p_value <= P_THRESHOLD
        threshold = search_threshold(train["thb_trend"].dropna().values, train["xau_t1"].dropna().values)

        for d in month_dates:
            trend = df.loc[d, "thb_trend"]
            pos = 0.0
            if edge_active and not pd.isna(trend):
                if trend > threshold:
                    pos = -1.0
                elif trend < -threshold:
                    pos = 1.0
            y = df.loc[d, "xau_t1"]
            ret = pos * y - TC * abs(pos - prev_pos)
            prev_pos = pos
            equity *= np.exp(ret)
            records.append({
                "date": d,
                "position": pos,
                "thb_trend": float(trend),
                "p_value": float(p_value),
                "y_pred": float(-trend) if pos != 0 else 0.0,
                "xau_t1": float(y),
                "strategy_ret": float(ret),
                "equity": float(equity),
            })

        month_records.append({
            "month": str(month),
            "p_value": float(p_value),
            "edge_active": bool(edge_active),
            "threshold": threshold,
            "n_train": int(len(train)),
            "n_test": int(len(month_dates)),
        })

    result = pd.DataFrame(records).set_index("date").sort_index()
    buyhold = np.exp(result["xau_t1"].cumsum())
    strat_perf = performance(result["strategy_ret"], result["equity"])
    bh_perf = performance(result["xau_t1"], buyhold)

    print(f"Graph edge filter: TREND_WINDOW={TREND_WINDOW}, P_THRESHOLD={P_THRESHOLD}, MAX_LAG={MAX_LAG}, TC={TC*100:.4f}%")
    print(f"Total OOS days: {len(result)}")
    print(f"Date range: {result.index.min().date()} to {result.index.max().date()}")
    print()

    print("=== Graph edge filter (walk-forward OOS) ===")
    for k, v in strat_perf.items():
        print(f"  {k}: {v:.4f}")
    print()

    print("=== Buy-and-hold XAU (same days) ===")
    for k, v in bh_perf.items():
        print(f"  {k}: {v:.4f}")
    print()

    result.to_csv(DATA / "trended_graph_equity.csv")
    summary = {
        "trend_window": TREND_WINDOW,
        "p_threshold": P_THRESHOLD,
        "max_lag": MAX_LAG,
        "lookback_days": LOOKBACK,
        "tc_per_trade": TC,
        "n_months": len(month_records),
        "n_days": int(len(result)),
        "strategy_metrics": strat_perf,
        "buyhold_metrics": bh_perf,
        "monthly_thresholds": month_records,
        "note": "THB->XAU Granger-causality edge as a regime filter. Research only.",
    }
    (DATA / "trended_graph_results.json").write_text(json.dumps(summary, indent=2))
    print("Saved: data/trended_graph_equity.csv, data/trended_graph_results.json")


if __name__ == "__main__":
    print("__main__ guard entered", flush=True)
    main()
