"""Walk-forward Singular Spectrum Analysis (SSA) trend strategy.

For each month, fit SSA to USD/THB log returns over the training window. Use the
leading r components to build a linear filter that reconstructs a denoised THB
return. The position follows the sign of the SSA-denoised THB trend, with the
XAU t+1 return as the target.

Research only, not a live trading strategy.

Usage:
    L=20 R=2 TREND_WINDOW=2 .venv/bin/python trended_ssa.py
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
L = int(os.environ.get("L", "20"))          # SSA embedding dimension
R = int(os.environ.get("R", "2"))           # number of leading SSA components
TREND_WINDOW = int(os.environ.get("TREND_WINDOW", "2"))
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
    df["xau_t1"] = logdf["xau"].shift(-1) - logdf["xau"]
    return df.dropna()


def ssa_filter_weights(thb, l, r):
    """Return P_last, a length-l vector of weights for the latest SSA reconstruction."""
    if len(thb) < l:
        return None
    # Trajectory matrix (l x k)
    k = len(thb) - l + 1
    X = np.empty((l, k), dtype=np.float64)
    for i in range(k):
        X[:, i] = thb[i : i + l]
    # SVD of trajectory matrix
    U, s, _ = np.linalg.svd(X, full_matrices=False)
    Ur = U[:, :r]
    # P = Ur @ Ur.T; we only need the last row (latest time component)
    P_last = Ur[-1, :] @ Ur.T
    return P_last


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
    thb = df["thb_ret"].values
    xau = df["xau_t1"].values
    dates = df.index
    n = len(df)

    # Precompute month map and positions
    month_map = pd.Series(dates).dt.to_period("M")
    months = dates.to_period("M").unique()
    pos_map = {d: i for i, d in enumerate(dates)}

    records = []
    prev_pos = 0.0
    equity = 1.0
    month_records = []

    for month in months:
        month_dates = dates[month_map == month]
        if len(month_dates) == 0:
            continue
        p0 = pos_map[month_dates[0]]

        # training positions: LOOKBACK days before month start
        train_start = max(0, p0 - LOOKBACK)
        train_pos = np.arange(train_start, p0)

        if len(train_pos) < L + TREND_WINDOW:
            for d in month_dates:
                records.append({
                    "date": d,
                    "position": 0.0,
                    "thb_trend": 0.0,
                    "xau_t1": xau[pos_map[d]],
                    "strategy_ret": 0.0,
                    "equity": equity,
                })
            continue

        # Fit SSA on training THB returns
        thb_train = thb[train_pos]
        P_last = ssa_filter_weights(thb_train, L, R)
        if P_last is None:
            for d in month_dates:
                records.append({
                    "date": d,
                    "position": 0.0,
                    "thb_trend": 0.0,
                    "xau_t1": xau[pos_map[d]],
                    "strategy_ret": 0.0,
                    "equity": equity,
                })
            continue

        # Compute SSA reconstruction for all relevant positions: from train_pos[L-1] to end of month
        p_end = pos_map[month_dates[-1]]
        p_start = train_pos[L - 1]
        recon = np.full(n, np.nan)
        for p in range(p_start, p_end + 1):
            recon[p] = P_last @ thb[p - L + 1 : p + 1]

        # SSA-denoised THB trend: rolling sum of recon over TREND_WINDOW
        thb_trend = np.full(n, np.nan)
        for p in range(p_start + TREND_WINDOW - 1, p_end + 1):
            thb_trend[p] = recon[p - TREND_WINDOW + 1 : p + 1].sum()

        # Threshold search on training subset (must have enough lags and non-NaN xau)
        train_fit_pos = np.arange(p_start + TREND_WINDOW - 1, p0)
        if len(train_fit_pos) < 63:
            threshold = 0.0
        else:
            threshold = search_threshold(thb_trend[train_fit_pos], xau[train_fit_pos])

        # Out-of-sample test days
        for d in month_dates:
            p = pos_map[d]
            pos = 0.0
            if not np.isnan(thb_trend[p]):
                if thb_trend[p] > threshold:
                    pos = -1.0
                elif thb_trend[p] < -threshold:
                    pos = 1.0
            y = xau[p]
            ret = pos * y - TC * abs(pos - prev_pos)
            prev_pos = pos
            equity *= np.exp(ret)
            records.append({
                "date": d,
                "position": pos,
                "thb_trend": float(thb_trend[p] if not np.isnan(thb_trend[p]) else 0.0),
                "xau_t1": float(y),
                "strategy_ret": float(ret),
                "equity": float(equity),
            })

        month_records.append({
            "month": str(month),
            "threshold": threshold,
            "n_train": int(len(train_pos)),
            "n_test": int(len(month_dates)),
        })

    result = pd.DataFrame(records).set_index("date").sort_index()
    buyhold = np.exp(result["xau_t1"].cumsum())
    strat_perf = performance(result["strategy_ret"], result["equity"])
    bh_perf = performance(result["xau_t1"], buyhold)

    print(f"SSA: L={L}, R={R}, TREND_WINDOW={TREND_WINDOW}, LOOKBACK={LOOKBACK}, TC={TC*100:.4f}%")
    print(f"Total OOS days: {len(result)}")
    print(f"Date range: {result.index.min().date()} to {result.index.max().date()}")
    print()

    print("=== SSA trend (walk-forward OOS) ===")
    for k, v in strat_perf.items():
        print(f"  {k}: {v:.4f}")
    print()

    print("=== Buy-and-hold XAU (same days) ===")
    for k, v in bh_perf.items():
        print(f"  {k}: {v:.4f}")
    print()

    result.to_csv(DATA / "trended_ssa_equity.csv")
    summary = {
        "l": L,
        "r": R,
        "trend_window": TREND_WINDOW,
        "lookback_days": LOOKBACK,
        "tc_per_trade": TC,
        "n_months": len(month_records),
        "n_days": int(len(result)),
        "strategy_metrics": strat_perf,
        "buyhold_metrics": bh_perf,
        "monthly_thresholds": month_records,
        "note": "SSA-denoised THB trend with walk-forward training. Research only.",
    }
    (DATA / "trended_ssa_results.json").write_text(json.dumps(summary, indent=2))
    print("Saved: data/trended_ssa_equity.csv, data/trended_ssa_results.json")


if __name__ == "__main__":
    main()
