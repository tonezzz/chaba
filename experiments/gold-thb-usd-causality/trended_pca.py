"""Walk-forward PCA + k-NN for THB/XAU return windows.

Build a WINDOW-day return vector, project it onto N_COMPONENTS principal
components (fit on the training set), then find k nearest neighbors in the
projected space and use their next-day XAU returns as the forecast.

Research only, not a live trading strategy.

Usage:
    WINDOW=3 K=20 N_COMPONENTS=2 .venv/bin/python trended_pca.py
"""
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.decomposition import PCA
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).parent
DATA = ROOT / "data"
LOOKBACK = int(os.environ.get("LOOKBACK", "252"))
WINDOW = int(os.environ.get("WINDOW", "3"))
K = int(os.environ.get("K", "20"))
N_COMPONENTS = int(os.environ.get("N_COMPONENTS", "2"))
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


def predict(X_train, y_train, X_query, k, weighted):
    knn = NearestNeighbors(n_neighbors=min(k + 1, len(X_train)), metric="euclidean")
    knn.fit(X_train)
    distances, indices = knn.kneighbors(X_query)
    y_pred = []
    for i, (dists, idx) in enumerate(zip(distances, indices)):
        mask = idx != i
        dists = dists[mask][:k]
        idx = idx[mask][:k]
        if weighted:
            w = np.exp(-dists / (dists.mean() + 1e-12))
            w = w / w.sum()
            y_pred.append(float(np.dot(w, y_train[idx])))
        else:
            y_pred.append(float(y_train[idx].mean()))
    return np.array(y_pred)


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

        # Standardize then PCA (fit on training only)
        scaler = StandardScaler().fit(X_train)
        X_train_s = scaler.transform(X_train)
        pca = PCA(n_components=min(N_COMPONENTS, X_train_s.shape[1]))
        X_train_p = pca.fit_transform(X_train_s)

        # Search threshold on in-sample predictions
        train_pred = predict(X_train_p, y_train, X_train_p, K, WEIGHTED)
        threshold = search_threshold(train_pred, y_train)

        test_idx = np.where(month_mask)[0]
        X_test = X_all[test_idx]
        X_test_s = scaler.transform(X_test)
        X_test_p = pca.transform(X_test_s)
        y_test = y_all[test_idx]
        y_pred = predict(X_train_p, y_train, X_test_p, K, WEIGHTED)

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

    print(f"PCA-k-NN: WINDOW={WINDOW}, K={K}, N_COMPONENTS={N_COMPONENTS}, WEIGHTED={WEIGHTED}, TC={TC*100:.4f}%")
    print(f"Total OOS days: {len(result)}")
    print(f"Date range: {result.index.min().date()} to {result.index.max().date()}")
    print()

    print("=== PCA + k-NN strategy (walk-forward OOS) ===")
    for k, v in strat_perf.items():
        print(f"  {k}: {v:.4f}")
    print()

    print("=== Buy-and-hold XAU (same days) ===")
    for k, v in bh_perf.items():
        print(f"  {k}: {v:.4f}")
    print()

    result.to_csv(DATA / "trended_pca_equity.csv")
    summary = {
        "window": WINDOW,
        "k": K,
        "n_components": N_COMPONENTS,
        "weighted": WEIGHTED,
        "lookback_days": LOOKBACK,
        "tc_per_trade": TC,
        "n_months": len(month_records),
        "n_days": int(len(result)),
        "strategy_metrics": strat_perf,
        "buyhold_metrics": bh_perf,
        "monthly_thresholds": month_records,
        "note": "PCA + k-NN on THB/XAU return windows. Research only.",
    }
    (DATA / "trended_pca_results.json").write_text(json.dumps(summary, indent=2))
    print("Saved: data/trended_pca_equity.csv, data/trended_pca_results.json")


if __name__ == "__main__":
    main()
