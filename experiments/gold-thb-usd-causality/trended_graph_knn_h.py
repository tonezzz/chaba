"""Graph edge filter + k-NN with multi-day forecast horizon.

For each day, the k-NN predicts the H-day log return of XAU. Positions are
taken every H trading days and held for H days. The graph edge (THB->XAU)
acts as a monthly gate.

Research only.

Usage:
    WINDOW=2 K=30 H=2 .venv/bin/python trended_graph_knn_h.py
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
WINDOW = int(os.environ.get("WINDOW", "2"))
K = int(os.environ.get("K", "30"))
WEIGHTED = os.environ.get("WEIGHTED", "1") in ("1", "true", "True", "yes")
P_THRESHOLD = float(os.environ.get("P_THRESHOLD", "0.01"))
MAX_LAG = int(os.environ.get("MAX_LAG", "2"))
EDGE_LOOKBACK = int(os.environ.get("EDGE_LOOKBACK", "504"))
H = int(os.environ.get("H", "2"))
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
    rets["xau_t_h"] = logdf["xau"].shift(-H) - logdf["xau"]
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


def search_threshold(y_pred, y_true):
    best = {"sharpe": -np.inf, "threshold": 0.0}
    upper = np.percentile(np.abs(y_pred), 90)
    for c in np.linspace(0.0, upper, 21):
        signal = np.where(np.abs(y_pred) > c, np.sign(y_pred), 0.0)
        rets = signal * y_true
        if rets.std() == 0:
            continue
        # y_true is H-day log return, scale to annual
        sharpe = rets.mean() / rets.std() * np.sqrt(252 / H)
        if sharpe > best["sharpe"]:
            best = {"sharpe": sharpe, "threshold": float(c)}
    return best["threshold"]


def performance(rets, eq, period=H):
    rets = rets.dropna()
    if len(rets) == 0 or rets.std() == 0:
        return {"sharpe": 0.0, "annual_return": 0.0, "annual_vol": 0.0, "max_dd": 0.0, "win_rate": 0.0}
    running_max = eq.cummax()
    drawdown = eq / running_max - 1.0
    return {
        "sharpe": float(rets.mean() / rets.std() * np.sqrt(252 / period)),
        "annual_return": float(rets.mean() * 252 / period),
        "annual_vol": float(rets.std() * np.sqrt(252 / period)),
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
    X_all, dates = build_features(df, WINDOW)
    y_all = df.loc[dates, "xau_t_h"].values
    date_to_idx = {d: i for i, d in enumerate(dates)}

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

        raw_train = df[df.index < start].tail(EDGE_LOOKBACK)
        p_value = granger_p(raw_train)
        edge_active = p_value <= P_THRESHOLD

        if len(train_idx) < max(WINDOW + K, 63) or not edge_active:
            month_records.append({
                "month": str(month),
                "edge_active": bool(edge_active),
                "p_value": float(p_value),
                "threshold": 0.0,
                "n_train": int(len(train_idx)),
                "n_test": int(len(month_dates)),
            })
            continue

        X_train = X_all[train_idx]
        y_train = y_all[train_idx]

        scaler = StandardScaler().fit(X_train)
        X_train_s = scaler.transform(X_train)

        train_pred = predict(X_train_s, y_train, X_train_s, K, WEIGHTED)
        threshold = search_threshold(train_pred, y_train)

        test_idx = np.where(month_mask)[0]
        X_test = X_all[test_idx]
        X_test_s = scaler.transform(X_test)
        y_pred = predict(X_train_s, y_train, X_test_s, K, WEIGHTED)

        for i, d in enumerate(month_dates):
            # Map test day to the local index in the month_dates array
            local_i = i
            yp = y_pred[local_i]
            d_global = date_to_idx[d]

            if d_global % H != 0:
                continue

            pos = 0.0
            if yp > threshold:
                pos = 1.0
            elif yp < -threshold:
                pos = -1.0

            y_prev = y_all[d_global - H] if d_global >= H else 0.0
            ret = prev_pos * y_prev - TC * abs(pos - prev_pos)
            prev_pos = pos
            equity *= np.exp(ret)

            records.append({
                "date": d,
                "position": pos,
                "y_pred": float(yp),
                "p_value": float(p_value),
                "xau_t_h": float(y_prev),
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
    if len(result) == 0:
        print("No trade days.")
        return
    buyhold = np.exp(df.loc[result.index, "xau_t_h"].cumsum())
    strat_perf = performance(result["strategy_ret"], result["equity"])
    bh_perf = performance(df.loc[result.index, "xau_t_h"], buyhold)

    print(f"Graph+k-NN H={H}: WINDOW={WINDOW}, K={K}, P_THRESHOLD={P_THRESHOLD}, EDGE_LB={EDGE_LOOKBACK}, TC={TC*100:.4f}%")
    print(f"Total OOS trade days: {len(result)}")
    print(f"Date range: {result.index.min().date()} to {result.index.max().date()}")
    print()

    print("=== Graph+k-NN H-day (walk-forward OOS) ===")
    for k, v in strat_perf.items():
        print(f"  {k}: {v:.4f}")
    print()

    print("=== Buy-and-hold XAU H-day (same days) ===")
    for k, v in bh_perf.items():
        print(f"  {k}: {v:.4f}")
    print()

    result.to_csv(DATA / f"trended_graph_knn_h{H}_equity.csv")
    summary = {
        "window": WINDOW,
        "k": K,
        "h": H,
        "p_threshold": P_THRESHOLD,
        "max_lag": MAX_LAG,
        "edge_lookback": EDGE_LOOKBACK,
        "lookback_days": LOOKBACK,
        "tc_per_trade": TC,
        "n_months": len(month_records),
        "n_days": int(len(result)),
        "strategy_metrics": strat_perf,
        "buyhold_metrics": bh_perf,
        "monthly_thresholds": month_records,
        "note": f"k-NN pattern matcher with H={H}-day horizon, gated by THB->XAU Granger edge. Research only.",
    }
    (DATA / f"trended_graph_knn_h{H}_results.json").write_text(json.dumps(summary, indent=2))
    print(f"Saved: data/trended_graph_knn_h{H}_equity.csv, data/trended_graph_knn_h{H}_results.json")


if __name__ == "__main__":
    main()
