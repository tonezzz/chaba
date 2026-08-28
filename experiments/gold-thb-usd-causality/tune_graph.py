"""Grid search for the graph/Granger edge filter strategy.

For each combination of (LOOKBACK, MAX_LAG, P_THRESHOLD) this runs the same
walk-forward logic as trended_graph.py, reusing the same monthly Granger
p-values where possible. Results are written to data/graph_tune_results.json
and data/graph_tune_grid.csv.

Research only.
"""
import json
import os
import warnings
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import grangercausalitytests

warnings.filterwarnings("ignore", category=FutureWarning)

ROOT = Path(__file__).parent
DATA = ROOT / "data"
LOOKBACKS = [int(x) for x in os.environ.get("LOOKBACKS", "252,504").split(",")]
MAX_LAGS = [int(x) for x in os.environ.get("MAX_LAGS", "1,2,3,5").split(",")]
P_THRESHOLDS = [float(x) for x in os.environ.get("P_THRESHOLDS", "0.01,0.05,0.10,0.20").split(",")]
TC = float(os.environ.get("TC", "0.0005"))


def load():
    df = pd.read_csv(DATA / "aligned.csv", parse_dates=["date"])
    df = df.sort_values("date").dropna().set_index("date")
    logdf = np.log(df)
    df["thb_ret"] = logdf["thb"].diff()
    df["xau_ret"] = logdf["xau"].diff()
    df["thb_trend"] = df["thb_ret"].rolling(2).sum()
    df["xau_t1"] = logdf["xau"].shift(-1) - logdf["xau"]
    return df.dropna()


def granger_pvals(train, maxlag=5):
    data = train[["xau_ret", "thb_ret"]].dropna().values
    if len(data) < maxlag * 4 + 10:
        return np.full(maxlag, 1.0)
    try:
        tests = grangercausalitytests(data, maxlag=maxlag, verbose=False)
        return np.array([tests[lag][0]["ssr_ftest"][1] for lag in tests], dtype=float)
    except Exception:
        return np.full(maxlag, 1.0)


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


def metrics(rets, equity):
    rets = rets.dropna()
    if len(rets) == 0 or rets.std() == 0:
        return {"sharpe": 0.0, "annual_return": 0.0, "annual_vol": 0.0, "max_dd": 0.0, "win_rate": 0.0}
    running_max = equity.cummax()
    drawdown = equity / running_max - 1.0
    return {
        "sharpe": float(rets.mean() / rets.std() * np.sqrt(252)),
        "annual_return": float(rets.mean() * 252),
        "annual_vol": float(rets.std() * np.sqrt(252)),
        "max_dd": float(drawdown.min()),
        "win_rate": float((rets > 0).sum() / len(rets)),
    }


def main():
    df = load()
    dates = df.index
    n = len(df)
    thb_trend = df["thb_trend"].values
    xau1 = df["xau_t1"].values

    month_map = dates.to_period("M")
    months = month_map.unique()
    n_months = len(months)

    # p-values per month x lookback x maxlag (5)
    pvals = {lb: np.full((n_months, 5), 1.0) for lb in LOOKBACKS}
    thresholds = {lb: np.full(n_months, 0.0) for lb in LOOKBACKS}

    print("Computing Granger p-values and thresholds...")
    for mi, month in enumerate(months):
        idx = np.where(month_map == month)[0]
        p0 = idx[0]
        for lb in LOOKBACKS:
            train_start = max(0, p0 - lb)
            train = df.iloc[train_start:p0]
            pvals[lb][mi, :] = granger_pvals(train, maxlag=5)
            if len(train) >= 64:
                thresholds[lb][mi] = search_threshold(train["thb_trend"].dropna().values, train["xau_t1"].dropna().values)

    combos = list(product(LOOKBACKS, MAX_LAGS, P_THRESHOLDS))
    combo_pos = np.zeros((len(combos), n))
    combo_prev = np.zeros(len(combos))

    print(f"Walking forward for {len(combos)} combinations...")
    for mi, month in enumerate(months):
        idx = np.where(month_map == month)[0]
        p0 = idx[0]
        p_end = idx[-1]
        for ci, (lb, max_lag, p_thresh) in enumerate(combos):
            pmin = pvals[lb][mi, :max_lag].min()
            active = pmin <= p_thresh
            th = thresholds[lb][mi]
            for p in range(p0, p_end + 1):
                t = thb_trend[p]
                pos = 0.0
                if active and not np.isnan(t):
                    if t > th:
                        pos = -1.0
                    elif t < -th:
                        pos = 1.0
                y = xau1[p]
                ret = pos * y - TC * abs(pos - combo_prev[ci])
                combo_prev[ci] = pos
                combo_pos[ci, p] = ret

    # Compute metrics for each combo
    records = []
    for ci, (lb, max_lag, p_thresh) in enumerate(combos):
        rets = pd.Series(combo_pos[ci])
        eq = np.exp(rets.cumsum())
        m = metrics(rets, pd.Series(eq))
        records.append({
            "lookback": lb,
            "max_lag": max_lag,
            "p_threshold": p_thresh,
            **m,
        })
        print(f"lookback={lb} max_lag={max_lag} p={p_thresh:4.2f} -> "
              f"sharpe={m['sharpe']:.3f} ret={m['annual_return']:.3f} dd={m['max_dd']:.3f} "
              f"vol={m['annual_vol']:.3f} wr={m['win_rate']:.3f}")

    results = pd.DataFrame(records).sort_values("sharpe", ascending=False)
    print("\nTop 3 by Sharpe:")
    print(results.head(3).to_string(index=False))
    results.to_csv(DATA / "graph_tune_grid.csv", index=False)
    (DATA / "graph_tune_results.json").write_text(json.dumps(records, indent=2))
    print("Saved: data/graph_tune_grid.csv, data/graph_tune_results.json")


if __name__ == "__main__":
    main()
