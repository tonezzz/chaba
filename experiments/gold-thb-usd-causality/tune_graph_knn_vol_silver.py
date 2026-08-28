"""Grid search for graph edge + k-NN with silver and volatility targeting.

Search over WINDOW and K for the vol+silver variant, keeping TARGET_VOL=0.20,
P_THRESHOLD=0.01 and EDGE_LOOKBACK=504 fixed. Results are written to
data/tune_graph_knn_vol_silver_grid.csv and .json. Research only.
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
WINDOWS = [int(x) for x in os.environ.get("WINDOWS", "2,3,4,5").split(",")]
KS = [int(x) for x in os.environ.get("KS", "20,30,40,50").split(",")]
LOOKBACK = int(os.environ.get("LOOKBACK", "252"))
P_THRESHOLD = float(os.environ.get("P_THRESHOLD", "0.01"))
EDGE_LOOKBACK = int(os.environ.get("EDGE_LOOKBACK", "504"))
TC = float(os.environ.get("TC", "0.0005"))
TARGET_VOL = float(os.environ.get("TARGET_VOL", "0.20"))
MAX_LEVERAGE = float(os.environ.get("MAX_LEVERAGE", "2.0"))
WEIGHTED = True


def load():
    df = pd.read_csv(DATA / "aligned_silver.csv", parse_dates=["date"])
    df = df.sort_values("date").dropna().set_index("date")
    logdf = np.log(df)
    rets = logdf.diff().dropna()
    rets.columns = ["xau_ret", "thb_ret", "xag_ret"]
    rets["xau_t1"] = logdf["xau"].shift(-1) - logdf["xau"]
    return rets.dropna()


def build_features(df, window):
    rets = df[["thb_ret", "xau_ret", "xag_ret"]].values
    X = []
    dates = []
    for t in range(window - 1, len(rets)):
        X.append(rets[t - window + 1 : t + 1].ravel().astype(np.float64))
        dates.append(df.index[t])
    return np.array(X), pd.to_datetime(dates)


def granger_p(raw_train, maxlag=2):
    data = raw_train[["xau_ret", "thb_ret"]].dropna().values
    if len(data) < maxlag * 4 + 10:
        return 1.0
    try:
        tests = grangercausalitytests(data, maxlag=maxlag, verbose=False)
        return float(min(tests[lag][0]["ssr_ftest"][1] for lag in tests))
    except Exception:
        return 1.0


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


def metrics(rets, eq):
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
    all_dates = df.index

    # Precompute features for each window
    feature_data = {}
    for w in WINDOWS:
        X, fdates = build_features(df, w)
        y = df.loc[fdates, "xau_t1"].values
        feature_data[w] = {"X": X, "dates": fdates, "y": y}

    combos = list(product(WINDOWS, KS))
    combo_keys = {c: i for i, c in enumerate(combos)}
    n_combos = len(combos)

    ret_df = pd.DataFrame(0.0, index=all_dates, columns=range(n_combos))
    prev_pos = np.zeros(n_combos)

    max_k = max(KS)
    all_months = sorted({m for w in WINDOWS for m in feature_data[w]["dates"].to_period("M").unique()})

    for w in WINDOWS:
        X = feature_data[w]["X"]
        fdates = feature_data[w]["dates"]
        y = feature_data[w]["y"]
        month_map = pd.Series(fdates).dt.to_period("M")

        for month in all_months:
            test_mask = month_map == month
            test_idx = np.where(test_mask)[0]
            if len(test_idx) == 0:
                continue
            month_start = fdates[test_idx[0]]

            train_idx = np.array([i for i, d in enumerate(fdates) if d < month_start - pd.Timedelta(days=1)]).astype(int)
            train_idx = train_idx[-LOOKBACK:]
            if len(train_idx) < max(w + max_k, 63):
                continue

            X_train = X[train_idx]
            y_train = y[train_idx]
            scaler = StandardScaler().fit(X_train)
            X_train_s = scaler.transform(X_train)

            knn = NearestNeighbors(n_neighbors=min(max_k + 1, len(X_train)), metric="euclidean")
            knn.fit(X_train_s)

            dists_in, idx_in = knn.kneighbors(X_train_s)
            X_test_s = scaler.transform(X[test_idx])
            dists_te, idx_te = knn.kneighbors(X_test_s)

            # y_pred for all K
            y_pred_train = {k: [] for k in KS}
            y_pred_test = {k: [] for k in KS}
            thresholds = {k: 0.0 for k in KS}

            for k in KS:
                for i, (d, ix) in enumerate(zip(dists_in, idx_in)):
                    mask = ix != i
                    dd = d[mask][:k]
                    ii = ix[mask][:k]
                    if WEIGHTED:
                        ww = np.exp(-dd / (dd.mean() + 1e-12))
                        ww = ww / ww.sum()
                        y_pred_train[k].append(float(np.dot(ww, y_train[ii])))
                    else:
                        y_pred_train[k].append(float(y_train[ii].mean()))
                thresholds[k] = search_threshold(np.array(y_pred_train[k]), y_train)

                for d, ix in zip(dists_te, idx_te):
                    dd = d[:k]
                    ii = ix[:k]
                    if WEIGHTED:
                        ww = np.exp(-dd / (dd.mean() + 1e-12))
                        ww = ww / ww.sum()
                        y_pred_test[k].append(float(np.dot(ww, y_train[ii])))
                    else:
                        y_pred_test[k].append(float(y_train[ii].mean()))
                y_pred_test[k] = np.array(y_pred_test[k])

            # Graph p-value and volatility sizing (same for all K at this W)
            raw_train = df[df.index < month_start].tail(EDGE_LOOKBACK)
            p_value = granger_p(raw_train)
            active = p_value <= P_THRESHOLD

            daily_target = TARGET_VOL / np.sqrt(252)
            realized_vol = y_train.std()
            if realized_vol > 0 and not np.isnan(realized_vol):
                vol_size = min(MAX_LEVERAGE, daily_target / realized_vol)
            else:
                vol_size = 0.0

            for k in KS:
                yp = y_pred_test[k]
                th = thresholds[k]
                combo = (w, k)
                ci = combo_keys[combo]
                for i, p in enumerate(test_idx):
                    date = fdates[p]
                    pos = 0.0
                    if active:
                        if yp[i] > th:
                            pos = vol_size
                        elif yp[i] < -th:
                            pos = -vol_size
                    yv = y[p]
                    ret = pos * yv - TC * abs(pos - prev_pos[ci])
                    prev_pos[ci] = pos
                    ret_df.loc[date, ci] = ret

    # Compute metrics
    records = []
    for combo in combos:
        ci = combo_keys[combo]
        rets = ret_df[ci]
        eq = np.exp(rets.cumsum())
        m = metrics(rets, eq)
        records.append({
            "window": combo[0],
            "k": combo[1],
            "p_threshold": P_THRESHOLD,
            "edge_lookback": EDGE_LOOKBACK,
            **m,
        })
        print(f"W={combo[0]:<2} K={combo[1]:<2} -> "
              f"sharpe={m['sharpe']:.3f} ret={m['annual_return']:.3f} dd={m['max_dd']:.3f} "
              f"vol={m['annual_vol']:.3f} wr={m['win_rate']:.3f}")

    results = pd.DataFrame(records).sort_values("sharpe", ascending=False)
    print("\nTop 5 by Sharpe:")
    print(results.head(5).to_string(index=False))
    results.to_csv(DATA / "tune_graph_knn_vol_silver_grid.csv", index=False)
    (DATA / "tune_graph_knn_vol_silver_results.json").write_text(json.dumps(records, indent=2))
    print("Saved: data/tune_graph_knn_vol_silver_grid.csv, data/tune_graph_knn_vol_silver_results.json")


if __name__ == "__main__":
    main()
