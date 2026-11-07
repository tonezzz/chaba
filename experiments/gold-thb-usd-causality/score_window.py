"""First scored window for lab card lab-gold-thb-causality.

Metric under test (from the card): out-of-sample directional accuracy > 60%
over 30 daily predictions.

Two variants of the "small causality model" (THB return -> next-day XAU/USD
direction) are scored walk-forward, monthly-recalibrated like walkforward.py:

  - threshold: predict -1/+1 only when |thb_trend| exceeds a Sharpe-searched
    threshold fit on the prior LOOKBACK days (same rule as walkforward.py).
    A "prediction" is a day with a nonzero call.
  - always: predict -sign(thb_trend) every day (threshold forced to 0) --
    the purest form of the causality claim; every day is a prediction.

For each variant we score the most recent WINDOW predictions (directional
accuracy vs sign of realized next-day XAU return), the full OOS span, and a
naive always-up baseline on the same days for context.

This is research code, not a live trading strategy.

Usage:
    .venv/bin/python score_window.py            # after analyze.py
    WINDOW=30 TREND_WINDOW=1 .venv/bin/python score_window.py
"""
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import binomtest
from statsmodels.stats.proportion import proportion_confint

ROOT = Path(__file__).parent
DATA = ROOT / "data"
LOOKBACK = int(os.environ.get("LOOKBACK", "252"))
TREND_WINDOW = int(os.environ.get("TREND_WINDOW", "1"))
WINDOW = int(os.environ.get("WINDOW", "30"))
MIN_TRAIN = 126


def load():
    if not (DATA / "returns.csv").exists():
        print("Run analyze.py first to generate data/returns.csv", file=sys.stderr)
        raise SystemExit(1)
    df = pd.read_csv(DATA / "returns.csv", parse_dates=["date"])
    df = df.sort_values("date").dropna()
    df = df.set_index("date")
    df["xau_t1"] = df["xau_ret"].shift(-1)
    df["thb_trend"] = df["thb_ret"].rolling(TREND_WINDOW).sum()
    return df.dropna()


def search_threshold(train, signal_col="thb_trend", target_col="xau_t1"):
    """Same Sharpe-search as walkforward.py, cost-free for threshold pick."""
    best = {"sharpe": -np.inf, "threshold": 0.0}
    upper = train[signal_col].abs().quantile(0.75)
    if upper == 0 or not np.isfinite(upper):
        return 0.0
    for c in np.linspace(0.0, upper, 21):
        signal = pd.Series(0.0, index=train.index)
        signal[train[signal_col] > c] = -1.0
        signal[train[signal_col] < -c] = 1.0
        rets = signal * train[target_col]
        if rets.std() == 0:
            continue
        sharpe = rets.mean() / rets.std() * np.sqrt(252)
        if sharpe > best["sharpe"]:
            best = {"sharpe": sharpe, "threshold": float(c)}
    return best["threshold"]


def score(pred, name):
    """Score a predictions frame (cols: date, signal, actual_ret)."""
    p = pred[pred["signal"] != 0].copy()
    p = p[p["actual_ret"] != 0]  # flat next-day return is not a direction
    p["correct"] = (np.sign(p["signal"]) == np.sign(p["actual_ret"])).astype(float)
    win = p.tail(WINDOW)
    baseline_up = float((win["actual_ret"] > 0).mean()) if len(win) else None
    roll = p["correct"].rolling(WINDOW).mean().dropna()
    window = {
        "n_predictions": int(len(win)),
        "from": str(win["date"].min().date()) if len(win) else None,
        "to": str(win["date"].max().date()) if len(win) else None,
        "n_correct": int(win["correct"].sum()) if len(win) else 0,
        "directional_accuracy": round(float(win["correct"].mean()), 4) if len(win) else None,
        "meets_metric_gt_60pct": bool(len(win) == WINDOW and win["correct"].mean() > 0.60),
        "naive_always_up_accuracy_same_days": round(baseline_up, 4) if baseline_up is not None else None,
    }
    if len(win):
        k, n = int(win["correct"].sum()), len(win)
        lo, hi = proportion_confint(k, n, alpha=0.10, method="wilson")
        window["wilson90_ci"] = [round(float(lo), 4), round(float(hi), 4)]
        window["p_value_vs_50pct"] = round(float(binomtest(k, n, 0.5, alternative="greater").pvalue), 4)
        window["p_value_vs_naive_baseline"] = round(
            float(binomtest(k, n, baseline_up, alternative="greater").pvalue), 4
        )
    return {
        "variant": name,
        "oos_days_with_prediction": int(len(p)),
        "oos_first_prediction": str(p["date"].min().date()) if len(p) else None,
        "oos_last_prediction": str(p["date"].max().date()) if len(p) else None,
        "oos_accuracy": round(float(p["correct"].mean()), 4) if len(p) else None,
        "rolling_window_stats": {
            "n_windows": int(len(roll)),
            "mean_accuracy": round(float(roll.mean()), 4) if len(roll) else None,
            "min_accuracy": round(float(roll.min()), 4) if len(roll) else None,
            "max_accuracy": round(float(roll.max()), 4) if len(roll) else None,
            "share_of_windows_above_60pct": round(float((roll > 0.60).mean()), 4) if len(roll) else None,
        },
        "window": window,
        "predictions": p,
    }


def main():
    df = load()
    months = df.index.to_period("M").unique()

    rows = []
    month_log = []
    for month in months:
        month_dates = df[df.index.to_period("M") == month]
        if len(month_dates) == 0:
            continue
        start = month_dates.index[0]
        train = df[df.index < start].tail(LOOKBACK)
        if len(train) < MIN_TRAIN:
            month_log.append({"month": str(month), "threshold": None, "n_train": int(len(train))})
            continue  # warm-up: no predictions, mirrors walkforward.py flat months
        threshold = search_threshold(train)
        month_log.append({"month": str(month), "threshold": round(threshold, 6), "n_train": int(len(train))})
        for date, row in month_dates.iterrows():
            thb_trend = row["thb_trend"]
            sig_thr = -1.0 if thb_trend > threshold else (1.0 if thb_trend < -threshold else 0.0)
            sig_alw = -1.0 if thb_trend > 0 else (1.0 if thb_trend < 0 else 0.0)
            rows.append({
                "date": date,
                "month": str(month),
                "thb_trend": float(thb_trend),
                "threshold": threshold,
                "signal_threshold": sig_thr,
                "signal_always": sig_alw,
                "actual_xau_ret": float(row["xau_t1"]),
            })

    pred = pd.DataFrame(rows)
    if pred.empty:
        print("No out-of-sample days produced (insufficient history).", file=sys.stderr)
        raise SystemExit(1)

    thr = score(pred.rename(columns={"signal_threshold": "signal", "actual_xau_ret": "actual_ret"}), "threshold")
    alw = score(pred.rename(columns={"signal_always": "signal", "actual_xau_ret": "actual_ret"}), "always")

    # Merge per-day correctness for the CSV log
    pred["correct_threshold"] = np.nan
    pred.loc[thr["predictions"].index, "correct_threshold"] = thr["predictions"]["correct"]
    pred["correct_always"] = np.nan
    pred.loc[alw["predictions"].index, "correct_always"] = alw["predictions"]["correct"]
    pred.to_csv(DATA / "predictions.csv", index=False)

    for r in (thr, alw):
        w = r["window"]
        print(f"=== {r['variant']} model ===")
        print(f"  OOS predictions: {r['oos_days_with_prediction']} "
              f"({r['oos_first_prediction']} .. {r['oos_last_prediction']})")
        print(f"  OOS accuracy: {r['oos_accuracy']}")
        print(f"  Last-{WINDOW} window: {w['from']} .. {w['to']} "
              f"({w['n_predictions']} predictions)")
        print(f"  Window accuracy: {w['directional_accuracy']} "
              f"({w['n_correct']}/{w['n_predictions']}) "
              f"metric>60%: {w['meets_metric_gt_60pct']}")
        print(f"  Wilson 90% CI: {w.get('wilson90_ci')}  "
              f"p(>50%)={w.get('p_value_vs_50pct')}  "
              f"p(>naive)={w.get('p_value_vs_naive_baseline')}")
        print(f"  Naive always-up on same days: {w['naive_always_up_accuracy_same_days']}")
        rs = r["rolling_window_stats"]
        print(f"  Rolling-{WINDOW} accuracy over OOS: mean={rs['mean_accuracy']} "
              f"min={rs['min_accuracy']} max={rs['max_accuracy']} "
              f"share>60%={rs['share_of_windows_above_60pct']} ({rs['n_windows']} windows)")
        print()

    summary = {
        "scored_at": str(pd.Timestamp.now().date()),
        "data_end": str(df.index.max().date()),
        "params": {"lookback": LOOKBACK, "trend_window": TREND_WINDOW, "window": WINDOW, "min_train": MIN_TRAIN},
        "metric_definition": "directional accuracy = share of nonzero-signal days where sign(signal) == sign(next-day xau return)",
        "threshold_model": {k: v for k, v in thr.items() if k != "predictions"},
        "always_model": {k: v for k, v in alw.items() if k != "predictions"},
        "monthly_thresholds": month_log,
        "note": "First scored window for lab-gold-thb-causality. Research only.",
    }
    (DATA / "scored_window.json").write_text(json.dumps(summary, indent=2))
    print("Saved: data/predictions.csv, data/scored_window.json")


if __name__ == "__main__":
    main()
