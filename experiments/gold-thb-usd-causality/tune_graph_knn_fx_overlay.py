"""Grid search KFX and TC_FX for the FX pre-positioning overlay.

Fixes the gold graph+k-NN (WINDOW, K, P_THRESHOLD, EDGE_LOOKBACK) and searches
over KFX and TC_FX for the USD/THB cash-timing overlay. Results written to
data/graph_knn_fx_overlay_tune_grid.csv and data/graph_knn_fx_overlay_tune_results.json.
Research only.
"""
import json
import os
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
WINDOW = int(os.environ.get("WINDOW", "2"))
K = int(os.environ.get("K", "30"))
KFXS = [int(x) for x in os.environ.get("KFXS", "10,20,30,50").split(",")]
TC_FXS = [float(x) for x in os.environ.get("TC_FXS", "0.0,0.0005,0.001,0.002,0.005").split(",")]
P_THRESHOLD = float(os.environ.get("P_THRESHOLD", "0.01"))
MAX_LAG = int(os.environ.get("MAX_LAG", "2"))
EDGE_LOOKBACK = int(os.environ.get("EDGE_LOOKBACK", "504"))
LOOKBACK = int(os.environ.get("LOOKBACK", "252"))
WEIGHTED = True
TC = float(os.environ.get("TC", "0.0005"))


def load():
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
    X = []
    dates = []
    for t in range(window - 1, len(rets)):
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


def granger_p(raw_train, maxlag=2):
    data = raw_train[["xau_ret", "thb_ret"]].dropna().values
    if len(data) < maxlag * 4 + 10:
        return 1.0
    try:
        tests = grangercausalitytests(data, maxlag=maxlag, verbose=False)
        return float(min(tests[lag][0]["ssr_ftest"][1] for lag in tests))
    except Exception:
        return 1.0


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


def metrics(rets, eq):
    mask = np.isfinite(rets)
    rets = rets[mask]
    eq = eq[mask]
    if len(rets) == 0 or rets.std() == 0:
        return {"sharpe": 0.0, "annual_return": 0.0, "annual_vol": 0.0, "max_dd": 0.0, "win_rate": 0.0}
    running_max = np.maximum.accumulate(eq)
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
    y_gold = df.loc[dates, "xau_t1"].values
    y_fx = df.loc[dates, "thb_t1"].values
    n_days = len(dates)

    month_map = pd.Series(dates).dt.to_period("M")
    months = month_map.unique()

    max_k = max(K, max(KFXS))

    # Store, for each day, the gold position and the USD/THB cash position for each KFX
    g_arr = np.zeros(n_days)
    c_arr = {kfx: np.zeros(n_days) for kfx in KFXS}
    y_gold_arr = y_gold.copy()
    y_fx_arr = y_fx.copy()

    for month in months:
        test_mask = month_map == month
        test_idx = np.where(test_mask)[0]
        if len(test_idx) == 0:
            continue
        month_start = dates[test_idx[0]]

        # k-NN train
        train_idx = np.array([i for i, d in enumerate(dates) if d < month_start - pd.Timedelta(days=1)]).astype(int)
        train_idx = train_idx[-LOOKBACK:]
        if len(train_idx) < max(WINDOW + max_k, 63):
            continue

        # Graph edge
        raw_train = df[df.index < month_start].tail(EDGE_LOOKBACK)
        p_value = granger_p(raw_train)
        edge_active = p_value <= P_THRESHOLD
        if not edge_active:
            for i in test_idx:
                g_arr[i] = 0.0
                for kfx in KFXS:
                    c_arr[kfx][i] = 0.0
            continue

        X_train = X_all[train_idx]
        yg_train = y_gold[train_idx]
        yf_train = y_fx[train_idx]

        scaler = StandardScaler().fit(X_train)
        X_train_s = scaler.transform(X_train)

        # Use one k-NN with max_k + 1 neighbors
        knn = NearestNeighbors(n_neighbors=min(max_k + 1, len(X_train)), metric="euclidean")
        knn.fit(X_train_s)

        # In-sample predictions for thresholds
        dists_in, idx_in = knn.kneighbors(X_train_s)
        yp_g_train = predict(X_train_s, yg_train, X_train_s, K, WEIGHTED)
        threshold_g = search_threshold(yp_g_train, yg_train)

        # Test predictions
        X_test_s = scaler.transform(X_all[test_idx])
        dists_te, idx_te = knn.kneighbors(X_test_s)

        yp_g = predict(X_train_s, yg_train, X_test_s, K, WEIGHTED)
        yp_f_train = {kfx: predict(X_train_s, yf_train, X_train_s, kfx, WEIGHTED) for kfx in KFXS}
        yp_f = {kfx: predict(X_train_s, yf_train, X_test_s, kfx, WEIGHTED) for kfx in KFXS}
        thresholds_f = {kfx: search_fx_threshold(yp_f_train[kfx], yf_train) for kfx in KFXS}

        for j, i in enumerate(test_idx):
            if yp_g[j] > threshold_g:
                g_arr[i] = 1.0
            elif yp_g[j] < -threshold_g:
                g_arr[i] = -1.0
            else:
                g_arr[i] = 0.0

            for kfx in KFXS:
                if g_arr[i] != 0.0:
                    c_arr[kfx][i] = 1.0
                else:
                    c_arr[kfx][i] = 1.0 if yp_f[kfx][j] > thresholds_f[kfx] else 0.0

    # Compute base return (excluding FX TC) and FX turnover for each KFX
    base_ret = {kfx: np.zeros(n_days) for kfx in KFXS}
    fx_turnover = {kfx: np.zeros(n_days) for kfx in KFXS}
    gold_turnover = np.zeros(n_days)

    g_prev = 0.0
    for i in range(n_days):
        gold_turnover[i] = abs(g_arr[i] - g_prev)
        g_prev = g_arr[i]

    for kfx in KFXS:
        c_prev = 0.0
        for i in range(n_days):
            fx_turnover[kfx][i] = abs(c_arr[kfx][i] - c_prev)
            c_prev = c_arr[kfx][i]
            yf_factor = 1.0 if (g_arr[i] != 0.0 or c_arr[kfx][i] == 1.0) else 0.0
            base_ret[kfx][i] = g_arr[i] * y_gold_arr[i] + yf_factor * y_fx_arr[i] - TC * gold_turnover[i]

    # Metrics for each (KFX, TC_FX) combo
    records = []
    for kfx in KFXS:
        for tc_fx in TC_FXS:
            rets = base_ret[kfx] - tc_fx * fx_turnover[kfx]
            eq = np.exp(rets.cumsum())
            m = metrics(rets, eq)
            records.append({
                "window": WINDOW,
                "k": K,
                "kfx": kfx,
                "tc_fx": tc_fx,
                **m,
            })
            print(f"W={WINDOW} K={K:<2} KFX={kfx:<2} TC_FX={tc_fx:.4f} -> "
                  f"sharpe={m['sharpe']:.3f} ret={m['annual_return']:.3f} "
                  f"dd={m['max_dd']:.3f} vol={m['annual_vol']:.3f} wr={m['win_rate']:.3f}")

    results = pd.DataFrame(records).sort_values("sharpe", ascending=False)
    print("\nTop 5 by Sharpe:")
    print(results.head(5).to_string(index=False))
    results.to_csv(DATA / "graph_knn_fx_overlay_tune_grid.csv", index=False)
    (DATA / "graph_knn_fx_overlay_tune_results.json").write_text(json.dumps(records, indent=2))
    print("Saved: data/graph_knn_fx_overlay_tune_grid.csv, data/graph_knn_fx_overlay_tune_results.json")


if __name__ == "__main__":
    main()
