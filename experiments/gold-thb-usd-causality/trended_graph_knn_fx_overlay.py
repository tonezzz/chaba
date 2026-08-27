"""Graph edge + k-NN with FX pre-positioning overlay.

Same THB->XAU graph+k-NN gold signal as the baseline, but the idle cash is
pre-positioned in USD when the next-day USD/THB return is expected positive,
and in THB when expected negative. The gold position is still XAU/USD. The
P/L is accounted in THB. Research only.

Usage:
    WINDOW=2 K=30 KFX=30 P_THRESHOLD=0.01 .venv/bin/python trended_graph_knn_fx_overlay.py
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
KFX = int(os.environ.get("KFX", "30"))
WEIGHTED = os.environ.get("WEIGHTED", "1") in ("1", "true", "True", "yes")
P_THRESHOLD = float(os.environ.get("P_THRESHOLD", "0.01"))
MAX_LAG = int(os.environ.get("MAX_LAG", "2"))
EDGE_LOOKBACK = int(os.environ.get("EDGE_LOOKBACK", "504"))
TC = float(os.environ.get("TC", "0.0005"))
TC_FX = float(os.environ.get("TC_FX", "0.0005"))


def load():
    if not (DATA / "aligned.csv").exists():
        print("data/aligned.csv is required. Run analyze.py first.", file=sys.stderr)
        raise SystemExit(1)
    df = pd.read_csv(DATA / "aligned.csv", parse_dates=["date"])
    df = df.sort_values("date").dropna().set_index("date")
    logdf = np.log(df)
    rets = logdf.diff().dropna()
    rets.columns = ["xau_ret", "thb_ret"]
    rets["xau_t1"] = logdf["xau"].shift(-1) - logdf["xau"]
    rets["thb_t1"] = logdf["thb"].shift(-1) - logdf["thb"]
    return rets.dropna()


def build_features(df, window):
    cols = ["thb_ret", "xau_ret"]
    rets = df[cols].values
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
        sharpe = rets.mean() / rets.std() * np.sqrt(252)
        if sharpe > best["sharpe"]:
            best = {"sharpe": sharpe, "threshold": float(c)}
    return best["threshold"]


def search_fx_threshold(y_pred, y_true):
    best = {"sharpe": -np.inf, "threshold": 0.0}
    lo = np.percentile(y_pred, 10)
    hi = np.percentile(y_pred, 90)
    for fc in np.linspace(lo, hi, 21):
        signal = (y_pred > fc).astype(float)
        rets = signal * y_true
        if rets.std() == 0:
            continue
        sharpe = rets.mean() / rets.std() * np.sqrt(252)
        if sharpe > best["sharpe"]:
            best = {"sharpe": sharpe, "threshold": float(fc)}
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
    y_gold = df.loc[dates, "xau_t1"].values
    y_fx = df.loc[dates, "thb_t1"].values

    month_map = pd.Series(dates).dt.to_period("M")
    months = dates.to_period("M").unique()

    records = []
    g_prev = 0.0
    c_prev = 0.0
    equity = 1.0
    month_records = []

    for month in months:
        month_mask = month_map == month
        month_dates = dates[month_mask]
        if len(month_dates) == 0:
            continue
        start = month_dates[0]

        # k-NN train
        train_end = start - pd.Timedelta(days=1)
        train_idx = np.array([i for i, d in enumerate(dates) if d < train_end]).astype(int)
        train_idx = train_idx[-LOOKBACK:]

        # Graph train
        raw_train = df[df.index < start].tail(EDGE_LOOKBACK)
        p_value = granger_p(raw_train)
        edge_active = p_value <= P_THRESHOLD

        if len(train_idx) < max(WINDOW + max(K, KFX), 63) or not edge_active:
            for d in month_dates:
                thb = df.loc[d, "thb_t1"]
                records.append({
                    "date": d,
                    "gold_pos": 0.0,
                    "usd_pos": 0.0,
                    "y_pred_gold": 0.0,
                    "y_pred_fx": 0.0,
                    "p_value": float(p_value),
                    "xau_t1": float(thb),
                    "strategy_ret": 0.0,
                    "equity": equity,
                })
            month_records.append({
                "month": str(month),
                "edge_active": bool(edge_active),
                "p_value": float(p_value),
                "threshold_gold": 0.0,
                "threshold_fx": 0.0,
                "n_train": int(len(train_idx)),
                "n_test": int(len(month_dates)),
            })
            continue

        X_train = X_all[train_idx]
        yg_train = y_gold[train_idx]
        yf_train = y_fx[train_idx]

        scaler = StandardScaler().fit(X_train)
        X_train_s = scaler.transform(X_train)

        # In-sample predictions for thresholds
        yp_g_train = predict(X_train_s, yg_train, X_train_s, K, WEIGHTED)
        threshold_g = search_threshold(yp_g_train, yg_train)

        yp_f_train = predict(X_train_s, yf_train, X_train_s, KFX, WEIGHTED)
        threshold_f = search_fx_threshold(yp_f_train, yf_train)

        # Test predictions
        test_idx = np.where(month_mask)[0]
        X_test_s = scaler.transform(X_all[test_idx])
        yp_g = predict(X_train_s, yg_train, X_test_s, K, WEIGHTED)
        yp_f = predict(X_train_s, yf_train, X_test_s, KFX, WEIGHTED)
        yg_test = y_gold[test_idx]
        yf_test = y_fx[test_idx]

        for d, ypg, ypf, yg, yth in zip(month_dates, yp_g, yp_f, yg_test, yf_test):
            g = 0.0
            if ypg > threshold_g:
                g = 1.0
            elif ypg < -threshold_g:
                g = -1.0

            # If we are in a gold position, we must be in USD to fund it.
            # If we are flat, pre-position USD or THB based on FX outlook.
            if g != 0.0:
                c = 1.0
            else:
                c = 1.0 if ypf > threshold_f else 0.0

            if g != 0.0:
                ret = g * yg + yth - TC * abs(g - g_prev) - TC_FX * abs(c - c_prev)
            else:
                ret = c * yth - TC_FX * abs(c - c_prev)

            g_prev = g
            c_prev = c
            equity *= np.exp(ret)

            records.append({
                "date": d,
                "gold_pos": g,
                "usd_pos": c,
                "y_pred_gold": float(ypg),
                "y_pred_fx": float(ypf),
                "p_value": float(p_value),
                "xau_t1": float(yg + yth),
                "strategy_ret": float(ret),
                "equity": float(equity),
            })

        month_records.append({
            "month": str(month),
            "edge_active": bool(edge_active),
            "p_value": float(p_value),
            "threshold_gold": threshold_g,
            "threshold_fx": threshold_f,
            "n_train": int(len(train_idx)),
            "n_test": int(len(test_idx)),
        })

    result = pd.DataFrame(records).set_index("date").sort_index()
    buyhold = np.exp(result["xau_t1"].cumsum())
    strat_perf = performance(result["strategy_ret"], result["equity"])
    bh_perf = performance(result["xau_t1"], buyhold)

    print(f"Graph+k-NN+FX overlay: WINDOW={WINDOW}, K={K}, KFX={KFX}, WEIGHTED={WEIGHTED}, P_THRESHOLD={P_THRESHOLD}, MAX_LAG={MAX_LAG}, EDGE_LB={EDGE_LOOKBACK}, TC={TC*100:.4f}%, TC_FX={TC_FX*100:.4f}%")
    print(f"Total OOS days: {len(result)}")
    print(f"Date range: {result.index.min().date()} to {result.index.max().date()}")
    print()

    print("=== Graph+k-NN+FX overlay (walk-forward OOS) ===")
    for k, v in strat_perf.items():
        print(f"  {k}: {v:.4f}")
    print()

    print("=== Buy-and-hold XAU/THB (same days) ===")
    for k, v in bh_perf.items():
        print(f"  {k}: {v:.4f}")
    print()

    result.to_csv(DATA / "trended_graph_knn_fx_overlay_equity.csv")
    summary = {
        "window": WINDOW,
        "k": K,
        "kfx": KFX,
        "weighted": WEIGHTED,
        "p_threshold": P_THRESHOLD,
        "max_lag": MAX_LAG,
        "edge_lookback": EDGE_LOOKBACK,
        "lookback_days": LOOKBACK,
        "tc_per_trade": TC,
        "tc_fx": TC_FX,
        "n_months": len(month_records),
        "n_days": int(len(result)),
        "strategy_metrics": strat_perf,
        "buyhold_metrics": bh_perf,
        "monthly_thresholds": month_records,
        "note": "XAU/USD graph+k-NN with USD/THB pre-positioning on idle cash. Research only.",
    }
    (DATA / "trended_graph_knn_fx_overlay_results.json").write_text(json.dumps(summary, indent=2))
    print("Saved: data/trended_graph_knn_fx_overlay_equity.csv, data/trended_graph_knn_fx_overlay_results.json")


if __name__ == "__main__":
    main()
