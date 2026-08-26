"""Walk-forward dynamic time warping (DTW) nearest-neighbor strategy.

For each day, build a window of USD/THB log returns. Find the K historical
windows with the smallest DTW distance. Use their future XAU returns as the
forecast. The position is flat when the forecast is below a threshold or the
current pattern is too far from its K-th neighbor (anomaly-style guard).

Research only, not a live trading strategy.

Usage:
    WINDOW=10 K=20 .venv/bin/python trended_dtw.py
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
WINDOW = int(os.environ.get("WINDOW", "10"))
K = int(os.environ.get("K", "20"))
WEIGHTED = os.environ.get("WEIGHTED", "1") in ("1", "true", "True", "yes")
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
    rets = df["thb_ret"].values
    n = len(rets)
    X = []
    dates = []
    for t in range(window - 1, n):
        X.append(rets[t - window + 1 : t + 1].astype(np.float64))
        dates.append(df.index[t])
    return np.array(X), pd.to_datetime(dates)


def y_for_dates(df, feature_dates):
    return df.loc[feature_dates, "xau_t1"].values


def dtw_distances(query, X):
    """Vectorized DTW distance between a 1-D query (W,) and n windows (n, W)."""
    n, w = X.shape
    # cost[n, i, j] = (query[i] - X[n, j])^2
    cost = (query.reshape(1, w, 1) - X.reshape(n, 1, w)) ** 2
    D = np.empty((n, w, w), dtype=np.float64)
    D[:, 0, 0] = cost[:, 0, 0]
    for i in range(1, w):
        D[:, i, 0] = D[:, i - 1, 0] + cost[:, i, 0]
        D[:, 0, i] = D[:, 0, i - 1] + cost[:, 0, i]
    for i in range(1, w):
        for j in range(1, w):
            D[:, i, j] = cost[:, i, j] + np.minimum(
                D[:, i - 1, j],
                np.minimum(D[:, i, j - 1], D[:, i - 1, j - 1])
            )
    return D[:, -1, -1]


def predict(X_train, y_train, X_query, k, weighted, exclude_self=None):
    """Return predicted y and distance to k-th neighbor for each query.
    exclude_self: if not None, a (n_query,) array giving the index in X_train to skip.
    """
    y_pred = []
    dist_k = []
    for qi, q in enumerate(X_query):
        dists = dtw_distances(q, X_train)
        if exclude_self is not None:
            dists[exclude_self[qi]] = np.inf
        idx = np.argsort(dists)[:k]
        d = dists[idx]
        dist_k.append(float(d[-1]))
        if weighted:
            w = np.exp(-d / (d.mean() + 1e-12))
            w = w / w.sum()
            y_pred.append(float(np.dot(w, y_train[idx])))
        else:
            y_pred.append(float(y_train[idx].mean()))
    return np.array(y_pred), np.array(dist_k)


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


def main():
    df = load()
    X_all, dates = build_features(df, WINDOW)
    y_all = y_for_dates(df, dates)
    month_map = pd.Series(dates).dt.to_period("M")
    months = dates.to_period("M").unique()

    records = []
    prev_pos = 0.0
    equity = 1.0
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

        if len(train_idx) < max(WINDOW + K, 63):
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

        # in-sample predictions for threshold search (leave-one-out)
        train_pred, _ = predict(X_train, y_train, X_train, K, WEIGHTED, exclude_self=np.arange(len(train_idx)))
        threshold = search_threshold(train_pred, y_train)

        test_idx = np.where(month_mask)[0]
        X_test = X_all[test_idx]
        y_test = y_all[test_idx]
        y_pred, dist_k = predict(X_train, y_train, X_test, K, WEIGHTED)

        # guard: go flat when the K-th neighbor is unusually far
        kth_threshold = np.percentile(
            [predict(X_train, y_train, X_train[ti].reshape(1, -1), K, False, exclude_self=np.array([ti]))[1][0]
             for ti in range(len(train_idx))],
            90,
        ) if len(train_idx) > K else np.inf

        for d, yp, y, dk in zip(month_dates, y_pred, y_test, dist_k):
            pos = 0.0
            if dk <= kth_threshold:
                if yp > threshold:
                    pos = 1.0
                elif yp < -threshold:
                    pos = -1.0
            ret = pos * y - TC * abs(pos - prev_pos)
            prev_pos = pos
            equity *= np.exp(ret)
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
            "kth_threshold": float(kth_threshold),
            "n_train": int(len(train_idx)),
            "n_test": int(len(test_idx)),
        })

    result = pd.DataFrame(records).set_index("date").sort_index()
    buyhold = np.exp(result["xau_t1"].cumsum())
    strat_perf = performance(result["strategy_ret"], result["equity"])
    bh_perf = performance(result["xau_t1"], buyhold)

    print(f"DTW: WINDOW={WINDOW}, K={K}, WEIGHTED={WEIGHTED}, TC={TC*100:.4f}%")
    print(f"Total OOS days: {len(result)}")
    print(f"Date range: {result.index.min().date()} to {result.index.max().date()}")
    print()

    print("=== DTW k-NN (walk-forward OOS) ===")
    for k, v in strat_perf.items():
        print(f"  {k}: {v:.4f}")
    print()

    print("=== Buy-and-hold XAU (same days) ===")
    for k, v in bh_perf.items():
        print(f"  {k}: {v:.4f}")
    print()

    result.to_csv(DATA / "trended_dtw_equity.csv")
    summary = {
        "window": WINDOW,
        "k": K,
        "weighted": WEIGHTED,
        "lookback_days": LOOKBACK,
        "tc_per_trade": TC,
        "n_months": len(month_records),
        "n_days": int(len(result)),
        "strategy_metrics": strat_perf,
        "buyhold_metrics": bh_perf,
        "monthly_thresholds": month_records,
        "note": "DTW nearest-neighbor on THB return windows. Research only.",
    }
    (DATA / "trended_dtw_results.json").write_text(json.dumps(summary, indent=2))
    print("Saved: data/trended_dtw_equity.csv, data/trended_dtw_results.json")


if __name__ == "__main__":
    main()
