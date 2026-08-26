"""Graph edge filter + k-NN with dynamic, in-sample K/WINDOW selection.

Each month, the graph edge (THB->XAU) is tested as usual. If active, the
previous LOOKBACK days are used to pick the (WINDOW, K) pair with the best
in-sample Sharpe for that month. The chosen pair is then used for the month's
out-of-sample predictions. Research only.

Usage:
    WINDOWS=2,3,4,5 KS=20,30,50 .venv/bin/python trended_graph_knn_dynamic.py
"""
import json
import os
import sys
import warnings
from itertools import product
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


def in_sample_sharpe(y_pred, y_true, threshold):
    signal = np.where(np.abs(y_pred) > threshold, np.sign(y_pred), 0.0)
    rets = signal * y_true
    if rets.std() == 0:
        return -np.inf
    return float(rets.mean() / rets.std() * np.sqrt(252))


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

    # Precompute features and y for each window
    feature_data = {}
    for w in WINDOWS:
        X, dates = build_features(df, w)
        y = df.loc[dates, "xau_t1"].values
        month_map = pd.Series(dates).dt.to_period("M")
        months = month_map.unique()
        feature_data[w] = {
            "X": X,
            "dates": dates,
            "y": y,
            "month_map": month_map,
            "months": months,
        }

    all_months = sorted({m for w in WINDOWS for m in feature_data[w]["months"]})
    max_k = max(KS)

    records = []
    prev_pos = 0.0
    equity = 1.0
    month_records = []

    for month in all_months:
        # Use the earliest window's month start as the month date; graph train uses calendar
        first_w = min(WINDOWS)
        fdata = feature_data[first_w]
        month_mask = fdata["month_map"] == month
        month_dates = fdata["dates"][month_mask]
        if len(month_dates) == 0:
            continue
        start = month_dates[0]

        # Graph train: EDGE_LOOKBACK days before month (raw df days)
        raw_train = df[df.index < start].tail(EDGE_LOOKBACK)
        p_value = granger_p(raw_train)
        edge_active = p_value <= P_THRESHOLD

        if not edge_active:
            month_records.append({
                "month": str(month),
                "edge_active": False,
                "p_value": float(p_value),
            })
            continue

        best = {"sharpe": -np.inf, "w": None, "k": None, "threshold": 0.0}
        candidates = []  # store test predictions and metadata for the best combo

        for w in WINDOWS:
            X = feature_data[w]["X"]
            dates = feature_data[w]["dates"]
            y = feature_data[w]["y"]
            month_map = feature_data[w]["month_map"]

            test_mask = month_map == month
            test_idx = np.where(test_mask)[0]
            if len(test_idx) == 0:
                continue

            train_end = start - pd.Timedelta(days=1)
            train_idx = np.array([i for i, d in enumerate(dates) if d < train_end]).astype(int)
            train_idx = train_idx[-LOOKBACK:]
            if len(train_idx) < max(w + max_k, 63):
                continue

            X_train = X[train_idx]
            y_train = y[train_idx]
            scaler = StandardScaler().fit(X_train)
            X_train_s = scaler.transform(X_train)
            X_test_s = scaler.transform(X[test_idx])
            y_test = y[test_idx]

            knn = NearestNeighbors(n_neighbors=min(max_k + 1, len(X_train)), metric="euclidean")
            knn.fit(X_train_s)
            dists_in, idx_in = knn.kneighbors(X_train_s)
            dists_te, idx_te = knn.kneighbors(X_test_s)

            for k in KS:
                y_pred_train = predict_from_dists(dists_in, idx_in, y_train, k, WEIGHTED)
                threshold = search_threshold(y_pred_train, y_train)
                is_sharpe = in_sample_sharpe(y_pred_train, y_train, threshold)

                if is_sharpe > best["sharpe"]:
                    y_pred_test = predict_from_dists(dists_te, idx_te, y_train, k, WEIGHTED)
                    best = {
                        "sharpe": is_sharpe,
                        "w": w,
                        "k": k,
                        "threshold": threshold,
                        "dates": dates[test_idx],
                        "y_test": y_test,
                        "y_pred": y_pred_test,
                    }

        if best["w"] is None:
            continue

        for d, yp, y in zip(best["dates"], best["y_pred"], best["y_test"]):
            pos = 0.0
            if yp > best["threshold"]:
                pos = 1.0
            elif yp < -best["threshold"]:
                pos = -1.0
            ret = pos * y - TC * abs(pos - prev_pos)
            prev_pos = pos
            equity *= np.exp(ret)
            records.append({
                "date": d,
                "position": pos,
                "y_pred": float(yp),
                "p_value": float(p_value),
                "xau_t1": float(y),
                "strategy_ret": float(ret),
                "equity": float(equity),
                "window": best["w"],
                "k": best["k"],
            })

        month_records.append({
            "month": str(month),
            "edge_active": True,
            "p_value": float(p_value),
            "threshold": best["threshold"],
            "window": best["w"],
            "k": best["k"],
            "is_sharpe": best["sharpe"],
        })

    result = pd.DataFrame(records).set_index("date").sort_index()
    buyhold = np.exp(result["xau_t1"].cumsum())
    strat_perf = performance(result["strategy_ret"], result["equity"])
    bh_perf = performance(result["xau_t1"], buyhold)

    print(f"Graph+k-NN dynamic: WINDOWS={WINDOWS}, KS={KS}, P_THRESHOLD={P_THRESHOLD}, EDGE_LB={EDGE_LOOKBACK}, TC={TC*100:.4f}%")
    print(f"Total OOS days: {len(result)}")
    print(f"Date range: {result.index.min().date()} to {result.index.max().date()}")
    print()

    print("=== Graph+k-NN dynamic (walk-forward OOS) ===")
    for k, v in strat_perf.items():
        print(f"  {k}: {v:.4f}")
    print()

    print("=== Buy-and-hold XAU (same days) ===")
    for k, v in bh_perf.items():
        print(f"  {k}: {v:.4f}")
    print()

    result.to_csv(DATA / "trended_graph_knn_dynamic_equity.csv")
    summary = {
        "windows": WINDOWS,
        "ks": KS,
        "p_threshold": P_THRESHOLD,
        "max_lag": MAX_LAG,
        "edge_lookback": EDGE_LOOKBACK,
        "lookback_days": LOOKBACK,
        "tc_per_trade": TC,
        "n_months": len(month_records),
        "n_days": int(len(result)),
        "strategy_metrics": strat_perf,
        "buyhold_metrics": bh_perf,
        "monthly_selections": month_records,
        "note": "Per-month dynamic K/WINDOW selection for graph+k-NN. Research only.",
    }
    (DATA / "trended_graph_knn_dynamic_results.json").write_text(json.dumps(summary, indent=2))
    print("Saved: data/trended_graph_knn_dynamic_equity.csv, data/trended_graph_knn_dynamic_results.json")


if __name__ == "__main__":
    main()
