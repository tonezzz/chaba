"""Graph edge filter + k-NN with a single K/WINDOW selected once on a hold-out period.

The best (WINDOW, K) pair is chosen by in-sample Sharpe on the period before
TRAIN_END, then held fixed for the OOS walk-forward from TRAIN_END onward. The
threshold is still re-estimated monthly. This removes the per-month selection
bias of the dynamic variant. Research only.

Usage:
    TRAIN_END=2017-01-01 WINDOWS=2,3,4,5 KS=20,30,50 .venv/bin/python trended_graph_knn_selected.py
"""
import json
import os
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import StandardScaler
from statsmodels.tsa.stattools import grangercausalitytests

warnings.filterwarnings("ignore", category=FutureWarning)

ROOT = Path(__file__).parent
DATA = ROOT / "data"
LOOKBACK = int(os.environ.get("LOOKBACK", "252"))
WINDOWS = [int(x) for x in os.environ.get("WINDOWS", "2,3,4,5").split(",")]
KS = [int(x) for x in os.environ.get("KS", "20,30,50").split(",")]
WEIGHTED = os.environ.get("WEIGHTED", "1") in ("1", "true", "True", "yes")
P_THRESHOLD = float(os.environ.get("P_THRESHOLD", "0.01"))
MAX_LAG = int(os.environ.get("MAX_LAG", "2"))
EDGE_LOOKBACK = int(os.environ.get("EDGE_LOOKBACK", "504"))
TC = float(os.environ.get("TC", "0.0005"))
TRAIN_END = pd.to_datetime(os.environ.get("TRAIN_END", "2017-01-01"))


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
        X.append(rets[t - window + 1 : t + 1].ravel().astype(np.float64))
        dates.append(df.index[t])
    return np.array(X), pd.to_datetime(dates)


def predict_from_dists(dists, idx, y_train, k, weighted):
    y_pred = []
    for i, (d, ix) in enumerate(zip(dists, idx)):
        mask = ix != i
        d = d[mask][:k]
        ix = ix[mask][:k]
        if weighted:
            w = np.exp(-d / (d.mean() + 1e-12))
            w = w / w.sum()
            y_pred.append(float(np.dot(w, y_train[ix])))
        else:
            y_pred.append(float(y_train[ix].mean()))
    return np.array(y_pred)


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


def granger_p(train, maxlag=2):
    data = train[["xau_ret", "thb_ret"]].dropna().values
    if len(data) < maxlag * 4 + 10:
        return 1.0
    try:
        tests = grangercausalitytests(data, maxlag=maxlag, verbose=False)
        pvals = [tests[lag][0]["ssr_ftest"][1] for lag in tests]
        return float(min(pvals))
    except Exception:
        return 1.0


def main():
    df = load()

    # Precompute features for each window
    feature_data = {}
    for w in WINDOWS:
        X, dates = build_features(df, w)
        y = df.loc[dates, "xau_t1"].values
        feature_data[w] = {"X": X, "dates": dates, "y": y}

    # In-sample selection of (W, K) on the period before TRAIN_END
    best = {"sharpe": -np.inf, "w": None, "k": None}
    max_k = max(KS)
    in_sample_records = []

    for w in WINDOWS:
        X = feature_data[w]["X"]
        dates = feature_data[w]["dates"]
        y = feature_data[w]["y"]

        is_mask = dates < TRAIN_END
        is_idx = np.where(is_mask)[0]
        if len(is_idx) < max(w + max_k, 63):
            continue

        X_is = X[is_idx]
        y_is = y[is_idx]
        scaler = StandardScaler().fit(X_is)
        X_is_s = scaler.transform(X_is)

        knn = NearestNeighbors(n_neighbors=min(max_k + 1, len(X_is)), metric="euclidean")
        knn.fit(X_is_s)
        dists, idx = knn.kneighbors(X_is_s)

        for k in KS:
            y_pred = predict_from_dists(dists, idx, y_is, k, WEIGHTED)
            threshold = search_threshold(y_pred, y_is)
            signal = np.where(np.abs(y_pred) > threshold, np.sign(y_pred), 0.0)
            rets = signal * y_is
            if rets.std() == 0:
                is_sharpe = -np.inf
            else:
                is_sharpe = float(rets.mean() / rets.std() * np.sqrt(252))
            in_sample_records.append({"w": w, "k": k, "sharpe": is_sharpe, "threshold": threshold})
            if is_sharpe > best["sharpe"]:
                best = {"sharpe": is_sharpe, "w": w, "k": k, "threshold": threshold}

    if best["w"] is None:
        print("No valid in-sample (W, K) found.", file=sys.stderr)
        raise SystemExit(1)

    W = best["w"]
    K = best["k"]

    # OOS walk-forward using the selected W, K
    X = feature_data[W]["X"]
    dates = feature_data[W]["dates"]
    y = feature_data[W]["y"]
    month_map = pd.Series(dates).dt.to_period("M")
    months = dates[dates >= TRAIN_END].to_period("M").unique()

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

        raw_train = df[df.index < start].tail(EDGE_LOOKBACK)
        p_value = granger_p(raw_train)
        edge_active = p_value <= P_THRESHOLD

        if len(train_idx) < max(W + K, 63) or not edge_active:
            for d in month_dates:
                records.append({
                    "date": d,
                    "position": 0.0,
                    "y_pred": 0.0,
                    "p_value": float(p_value),
                    "xau_t1": df.loc[d, "xau_t1"],
                    "strategy_ret": 0.0,
                    "equity": equity,
                })
            month_records.append({
                "month": str(month),
                "edge_active": bool(edge_active),
                "p_value": float(p_value),
                "threshold": 0.0,
                "n_train": int(len(train_idx)),
                "n_test": int(len(month_dates)),
            })
            continue

        X_train = X[train_idx]
        y_train = y[train_idx]
        scaler = StandardScaler().fit(X_train)
        X_train_s = scaler.transform(X_train)

        knn = NearestNeighbors(n_neighbors=min(K + 1, len(X_train)), metric="euclidean")
        knn.fit(X_train_s)
        dists_in, idx_in = knn.kneighbors(X_train_s)
        train_pred = predict_from_dists(dists_in, idx_in, y_train, K, WEIGHTED)
        threshold = search_threshold(train_pred, y_train)

        test_idx = np.where(month_mask)[0]
        X_test_s = scaler.transform(X[test_idx])
        y_test = y[test_idx]
        dists_te, idx_te = knn.kneighbors(X_test_s)
        y_pred = predict_from_dists(dists_te, idx_te, y_train, K, WEIGHTED)

        for d, yp, yv in zip(month_dates, y_pred, y_test):
            pos = 0.0
            if yp > threshold:
                pos = 1.0
            elif yp < -threshold:
                pos = -1.0
            ret = pos * yv - TC * abs(pos - prev_pos)
            prev_pos = pos
            equity *= np.exp(ret)
            records.append({
                "date": d,
                "position": pos,
                "y_pred": float(yp),
                "p_value": float(p_value),
                "xau_t1": float(yv),
                "strategy_ret": float(ret),
                "equity": float(equity),
            })

        month_records.append({
            "month": str(month),
            "edge_active": bool(edge_active),
            "p_value": float(p_value),
            "threshold": threshold,
            "n_train": int(len(train_idx)),
            "n_test": int(len(test_idx)),
        })

    result = pd.DataFrame(records).set_index("date").sort_index()
    buyhold = np.exp(result["xau_t1"].cumsum())
    strat_perf = performance(result["strategy_ret"], result["equity"])
    bh_perf = performance(result["xau_t1"], buyhold)

    print(f"Graph+k-NN selected: W={W}, K={K} (in-sample Sharpe {best['sharpe']:.4f})")
    print(f"In-sample selection records:")
    for r in in_sample_records:
        print(f"  W={r['w']} K={r['k']}: in-sample Sharpe={r['sharpe']:.4f}")
    print()
    print(f"P_THRESHOLD={P_THRESHOLD}, EDGE_LB={EDGE_LOOKBACK}, TC={TC*100:.4f}%")
    print(f"Total OOS days: {len(result)}")
    print(f"Date range: {result.index.min().date()} to {result.index.max().date()}")
    print()

    print("=== Graph+k-NN selected (walk-forward OOS) ===")
    for k, v in strat_perf.items():
        print(f"  {k}: {v:.4f}")
    print()

    print("=== Buy-and-hold XAU (same days) ===")
    for k, v in bh_perf.items():
        print(f"  {k}: {v:.4f}")
    print()

    result.to_csv(DATA / "trended_graph_knn_selected_equity.csv")
    summary = {
        "window": W,
        "k": K,
        "in_sample_records": in_sample_records,
        "p_threshold": P_THRESHOLD,
        "max_lag": MAX_LAG,
        "edge_lookback": EDGE_LOOKBACK,
        "lookback_days": LOOKBACK,
        "tc_per_trade": TC,
        "train_end": str(TRAIN_END.date()),
        "n_months": len(month_records),
        "n_days": int(len(result)),
        "strategy_metrics": strat_perf,
        "buyhold_metrics": bh_perf,
        "monthly_thresholds": month_records,
        "note": "Single (W,K) selected once on a pre-2017 hold-out, then monthly threshold. Research only.",
    }
    (DATA / "trended_graph_knn_selected_results.json").write_text(json.dumps(summary, indent=2))
    print("Saved: data/trended_graph_knn_selected_equity.csv, data/trended_graph_knn_selected_results.json")


if __name__ == "__main__":
    main()
