"""Walk-forward kernel-weighted forecast for THB/XAU return windows.

For each day, compute the Euclidean distance from the current 3-day THB/XAU
window to every window in the training set. The XAU forecast is the
similarity-weighted average of the training targets, using an RBF kernel.

This is the SSOT step 3: "Similarity-weighted forecast."

Research only, not a live trading strategy.

Usage:
    WINDOW=3 GAMMA=1.0 .venv/bin/python trended_weighted.py
"""
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial.distance import cdist
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).parent
DATA = ROOT / "data"
LOOKBACK = int(os.environ.get("LOOKBACK", "252"))
WINDOW = int(os.environ.get("WINDOW", "3"))
GAMMA = float(os.environ.get("GAMMA", "0.5"))
KERNEL = os.environ.get("KERNEL", "rbf")
TC = float(os.environ.get("TC", "0.0005"))


def load():
    if not (DATA / "aligned.csv").exists():
        print("Run analyze.py first to generate data/aligned.csv", file=sys.stderr)
        raise SystemExit(1)
    df = pd.read_csv(DATA / "aligned.csv", parse_dates=["date"])
    df = df.sort_values("date").dropna()
    df.set_index("date", inplace=True)
    logdf = np.log(df)
    rets = logdf.diff().dropna()
    rets.columns = ["xau_ret", "thb_ret"]
    rets["xau_t1"] = logdf["xau"].shift(-1) - logdf["xau"]
    return rets.dropna()


def build_features(df, window):
    rets = df[["thb_ret", "xau_ret"]].values
    n = len(rets)
    X = []
    dates = []
    for t in range(window - 1, n):
        vec = rets[t - window + 1 : t + 1].ravel().astype(np.float64)
        X.append(vec)
        dates.append(df.index[t])
    return np.array(X), pd.to_datetime(dates)


def y_for_dates(df, feature_dates):
    return df.loc[feature_dates, "xau_t1"].values


def search_threshold(y_pred, y_true):
    best = {"sharpe": -np.inf, "threshold": 0.0}
    upper = np.percentile(np.abs(y_pred), 90)
    for c in np.linspace(0.0, upper, 21):
        signal = np.where(np.abs(y_pred) > c, np.sign(y_pred), 0.0)
        rets = signal * y_true
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


def kernel_forecast(X_train, y_train, X_test, gamma, kernel):
    """Nadaraya-Watson kernel smoother over all training points."""
    distances = cdist(X_test, X_train, metric="euclidean")
    if kernel == "rbf":
        weights = np.exp(-gamma * distances ** 2)
    elif kernel == "laplace":
        weights = np.exp(-gamma * distances)
    elif kernel == "inverse":
        weights = 1.0 / (distances + 1e-12)
    else:
        raise ValueError(f"Unknown KERNEL: {kernel}")
    y_pred = (weights * y_train).sum(axis=1) / (weights.sum(axis=1) + 1e-12)
    return y_pred


def main():
    df = load()
    X_all, dates = build_features(df, WINDOW)
    y_all = y_for_dates(df, dates)
    month_map = pd.Series(dates).dt.to_period("M")
    months = dates.to_period("M").unique()

    records = []
    prev_pos = 0.0
    equity = 1.0
    running_max = 1.0
    month_records = []

    for month in months:
        month_mask = month_map == month
        month_dates = dates[month_mask]
        if len(month_dates) == 0:
            continue
        start = month_dates[0]

        train_end = start - pd.Timedelta(days=1)
        train_idx = np.array([i for i, d in enumerate(dates) if d < train_end]).astype(int)
        train_idx = train_idx[-LOOKBACK:]

        if len(train_idx) < 63:
            for d in month_dates:
                records.append({
                    "date": d,
                    "position": 0.0,
                    "y_pred": 0.0,
                    "xau_t1": df.loc[d, "xau_t1"],
                    "strategy_ret": 0.0,
                    "equity": equity,
                })
            continue

        X_train = X_all[train_idx]
        y_train = y_all[train_idx]

        # Standardize on training set
        scaler = StandardScaler().fit(X_train)
        X_train_s = scaler.transform(X_train)

        # In-sample forecast for threshold search
        train_pred = kernel_forecast(X_train_s, y_train, X_train_s, GAMMA, KERNEL)
        # Exclude self by averaging over all other points
        train_pred_corrected = []
        for i in range(len(train_pred)):
            # Remove the self-contribution: recompute with point i excluded
            mask = np.ones(len(y_train), dtype=bool)
            mask[i] = False
            dists = cdist([X_train_s[i]], X_train_s[mask], metric="euclidean")[0]
            if KERNEL == "rbf":
                w = np.exp(-GAMMA * dists ** 2)
            elif KERNEL == "laplace":
                w = np.exp(-GAMMA * dists)
            elif KERNEL == "inverse":
                w = 1.0 / (dists + 1e-12)
            train_pred_corrected.append(float(np.dot(w, y_train[mask]) / (w.sum() + 1e-12)))
        train_pred_corrected = np.array(train_pred_corrected)

        threshold = search_threshold(train_pred_corrected, y_train)

        test_idx = np.where(month_mask)[0]
        X_test = X_all[test_idx]
        X_test_s = scaler.transform(X_test)
        y_test = y_all[test_idx]
        y_pred = kernel_forecast(X_train_s, y_train, X_test_s, GAMMA, KERNEL)

        for d, yp, y in zip(month_dates, y_pred, y_test):
            pos = 0.0
            if yp > threshold:
                pos = 1.0
            elif yp < -threshold:
                pos = -1.0
            ret = pos * y - TC * abs(pos - prev_pos)
            prev_pos = pos
            equity *= np.exp(ret)
            running_max = max(running_max, equity)
            records.append({
                "date": d,
                "position": pos,
                "y_pred": float(yp),
                "xau_t1": float(y),
                "strategy_ret": float(ret),
                "equity": float(equity),
            })

        month_records.append({
            "month": str(month),
            "threshold": threshold,
            "n_train": int(len(train_idx)),
            "n_test": int(len(test_idx)),
        })

    result = pd.DataFrame(records).set_index("date").sort_index()
    buyhold = np.exp(result["xau_t1"].cumsum())
    strat_perf = performance(result["strategy_ret"], result["equity"])
    bh_perf = performance(result["xau_t1"], buyhold)

    print(f"Weighted: WINDOW={WINDOW}, GAMMA={GAMMA}, KERNEL={KERNEL}, TC={TC*100:.4f}%")
    print(f"Total OOS days: {len(result)}")
    print(f"Date range: {result.index.min().date()} to {result.index.max().date()}")
    print()

    print("=== Similarity-weighted forecast (walk-forward OOS) ===")
    for k, v in strat_perf.items():
        print(f"  {k}: {v:.4f}")
    print()

    print("=== Buy-and-hold XAU (same days) ===")
    for k, v in bh_perf.items():
        print(f"  {k}: {v:.4f}")
    print()

    result.to_csv(DATA / "trended_weighted_equity.csv")
    summary = {
        "window": WINDOW,
        "gamma": GAMMA,
        "kernel": KERNEL,
        "lookback_days": LOOKBACK,
        "tc_per_trade": TC,
        "n_months": len(month_records),
        "n_days": int(len(result)),
        "strategy_metrics": strat_perf,
        "buyhold_metrics": bh_perf,
        "monthly_thresholds": month_records,
        "note": "Similarity-weighted (kernel) forecast on THB/XAU windows. Research only.",
    }
    (DATA / "trended_weighted_results.json").write_text(json.dumps(summary, indent=2))
    print("Saved: data/trended_weighted_equity.csv, data/trended_weighted_results.json")


if __name__ == "__main__":
    main()
