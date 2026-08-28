"""k-NN Sharpe multi-head weighting for THB/XAU/XAG trading.

For each day, query a historical context memory for the K most similar past
regimes, compute each head's local Sharpe over those neighbors, and use a
softmax over local Sharpe to weight the three head positions.

Usage:
    K_MEM=50 TEMP=1.0 .venv/bin/python multi_head_knn_sharpe.py
"""
import json
import os
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings("ignore", category=FutureWarning)

# Shared hyper-parameters
os.environ.setdefault("LOOKBACK", "252")
os.environ.setdefault("WINDOW", "2")
os.environ.setdefault("K", "50")
os.environ.setdefault("WEIGHTED", "1")
os.environ.setdefault("P_THRESHOLD", "0.01")
os.environ.setdefault("MAX_LAG", "2")
os.environ.setdefault("EDGE_LOOKBACK", "504")
os.environ.setdefault("TC", "0.0005")
os.environ.setdefault("TARGET_VOL", "0.20")
os.environ.setdefault("MAX_LEVERAGE", "2.0")
os.environ.setdefault("ATR_WINDOW", "14")
os.environ.setdefault("K_MEM", "50")          # neighbors for context memory
os.environ.setdefault("TEMP", "1.0")          # softmax temperature

import trended_atr_sizing as atr
import trended_graph_knn_thb_xag as gkx
import trended_graph_knn_vol_silver as vks
from context import build_context_vectors
from memory import Memory

ROOT = Path(__file__).parent
DATA = ROOT / "data"
TC = float(os.environ["TC"])
MAX_LEVERAGE = float(os.environ["MAX_LEVERAGE"])
K_MEM = int(os.environ["K_MEM"])
TEMP = float(os.environ["TEMP"])


def load():
    if not (DATA / "aligned_silver.csv").exists():
        print("Run prepare_silver.py first", file=sys.stderr)
        raise SystemExit(1)
    df = pd.read_csv(DATA / "aligned_silver.csv", parse_dates=["date"])
    df = df.sort_values("date").dropna()
    df.set_index("date", inplace=True)
    logdf = np.log(df)
    rets = logdf.diff().dropna()
    rets.columns = ["xau_ret", "thb_ret", "xag_ret"]
    rets["xau_t1"] = logdf["xau"].shift(-1) - logdf["xau"]
    return rets.dropna()


def performance(rets, eq):
    rets = rets.dropna()
    if len(rets) == 0 or rets.std() == 0:
        return {
            "sharpe": 0.0,
            "annual_return": 0.0,
            "annual_vol": 0.0,
            "max_dd": 0.0,
            "win_rate": 0.0,
        }
    running_max = eq.cummax()
    drawdown = eq / running_max - 1.0
    return {
        "sharpe": float(rets.mean() / rets.std() * np.sqrt(252)),
        "annual_return": float(rets.mean() * 252),
        "annual_vol": float(rets.std() * np.sqrt(252)),
        "max_dd": float(drawdown.min()),
        "win_rate": float((rets > 0).sum() / len(rets)),
    }


def month_head_positions(df, X_all, y_all, dates, head_name, head_module, month, window, k, lookback, edge_lookback, p_threshold):
    """Return the per-day position vector for one head for one month."""
    month_map = pd.Series(dates).dt.to_period("M")
    month_mask = month_map == month
    test_idx = np.where(month_mask)[0]
    if len(test_idx) == 0:
        return np.array([])

    month_dates = dates[test_idx]
    start = month_dates[0]
    train_end = start - pd.Timedelta(days=1)
    train_idx = np.array([i for i, d in enumerate(dates) if d < train_end]).astype(int)
    train_idx = train_idx[-lookback:]

    raw_train = df[df.index < start].tail(edge_lookback)
    p_value = head_module.granger_p(raw_train)
    edge_active = p_value <= p_threshold

    n_min = max(window + k, 63)
    if len(train_idx) < n_min or not edge_active:
        return np.zeros(len(month_dates))

    X_train = X_all[train_idx]
    y_train = y_all[train_idx]
    scaler = StandardScaler().fit(X_train)
    X_train_s = scaler.transform(X_train)
    train_pred = head_module.predict(X_train_s, y_train, X_train_s, k, True)
    threshold = head_module.search_threshold(train_pred, y_train)

    X_test = X_all[test_idx]
    X_test_s = scaler.transform(X_test)
    y_test = y_all[test_idx]
    y_pred = head_module.predict(X_train_s, y_train, X_test_s, k, True)

    positions = np.zeros(len(month_dates))
    xau_rets = raw_train["xau_ret"]
    for j, (yp, y) in enumerate(zip(y_pred, y_test)):
        pos = 0.0
        if yp > threshold:
            pos = 1.0
        elif yp < -threshold:
            pos = -1.0

        if head_name == "atr_sizing" and pos != 0.0:
            atr = xau_rets.tail(int(os.environ["ATR_WINDOW"])).abs().mean()
            daily_vol = atr * np.sqrt(252)
            size = min(MAX_LEVERAGE, float(os.environ["TARGET_VOL"]) / daily_vol) if daily_vol > 0 else 0.0
            pos *= size
        elif head_name == "vol_silver" and pos != 0.0:
            daily_target = float(os.environ["TARGET_VOL"]) / np.sqrt(252)
            realized_vol = y_train.std()
            size = min(MAX_LEVERAGE, daily_target / realized_vol) if realized_vol > 0 and not np.isnan(realized_vol) else 0.0
            pos *= size
        positions[j] = pos
    return positions


def softmax(x, temp=1.0):
    x = x * temp
    x = x - np.max(x)
    e = np.exp(x)
    if e.sum() == 0:
        return np.ones_like(x) / len(x)
    return e / e.sum()


def main():
    df = load()
    window = int(os.environ["WINDOW"])
    k = int(os.environ["K"])
    lookback = int(os.environ["LOOKBACK"])
    edge_lookback = int(os.environ["EDGE_LOOKBACK"])
    p_threshold = float(os.environ["P_THRESHOLD"])

    X_atr, _ = atr.build_features(df, window)
    X_gkx, _ = gkx.build_features(df, window)
    X_vks, _ = vks.build_features(df, window)

    # Align dates across heads (same window, same df, so same length)
    _, d1 = atr.build_features(df, window)
    _, d2 = gkx.build_features(df, window)
    _, d3 = vks.build_features(df, window)
    assert len(d1) == len(d2) == len(d3)
    dates = d1
    y_all = df.loc[dates, "xau_t1"].values

    context_vectors, _ = build_context_vectors(df, dates)

    months = dates.to_period("M").unique()
    memory = Memory(k=K_MEM)

    records = []
    prev_pos = 0.0
    equity = 1.0
    month_records = []

    for m_idx, month in enumerate(months):
        # Prepare head positions for this month
        pos_atr = month_head_positions(df, X_atr, y_all, dates, "atr_sizing", atr, month, window, k, lookback, edge_lookback, p_threshold)
        pos_gkx = month_head_positions(df, X_gkx, y_all, dates, "graph_knn_thb_xag", gkx, month, window, k, lookback, edge_lookback, p_threshold)
        pos_vks = month_head_positions(df, X_vks, y_all, dates, "vol_silver", vks, month, window, k, lookback, edge_lookback, p_threshold)

        month_map = pd.Series(dates).dt.to_period("M")
        test_idx = np.where(month_map == month)[0]

        # Fit memory on all data before this month
        if m_idx > 0 and len(memory) >= K_MEM:
            memory.fit()

        month_contexts = []
        month_head_returns = []

        for j, day_idx in enumerate(test_idx):
            y = y_all[day_idx]
            head_pos = np.array([pos_atr[j], pos_gkx[j], pos_vks[j]])
            ctx = context_vectors[day_idx]

            # Query memory for similar past contexts
            neighbors = memory.query(ctx) if len(memory) >= K_MEM else None
            if neighbors is not None and len(neighbors) >= K_MEM:
                local_sharpe = np.zeros(3)
                for h in range(3):
                    rets = neighbors[:, h]
                    if rets.std() > 0:
                        local_sharpe[h] = rets.mean() / rets.std() * np.sqrt(252)
                weights = softmax(local_sharpe, TEMP)
            else:
                weights = np.ones(3) / 3.0

            final_pos = np.dot(weights, head_pos)
            final_pos = np.clip(final_pos, -MAX_LEVERAGE, MAX_LEVERAGE)
            ret = final_pos * y - TC * abs(final_pos - prev_pos)
            prev_pos = final_pos
            equity *= np.exp(ret)

            gross_head_returns = head_pos * y
            month_contexts.append(ctx)
            month_head_returns.append(gross_head_returns)

            records.append({
                "date": dates[day_idx],
                "position": float(final_pos),
                "weight_atr": float(weights[0]),
                "weight_gkx": float(weights[1]),
                "weight_vks": float(weights[2]),
                "pos_atr": float(head_pos[0]),
                "pos_gkx": float(head_pos[1]),
                "pos_vks": float(head_pos[2]),
                "xau_t1": float(y),
                "strategy_ret": float(ret),
                "equity": float(equity),
            })

        # Commit this month to memory (after all positions are realized)
        for ctx, hret, day_idx in zip(month_contexts, month_head_returns, test_idx):
            memory.append(ctx, hret, dates[day_idx])

        month_records.append({
            "month": str(month),
            "n_days": int(len(test_idx)),
            "memory_size": int(len(memory)),
        })

    result = pd.DataFrame(records).set_index("date").sort_index()
    buyhold = np.exp(result["xau_t1"].cumsum())
    strat_perf = performance(result["strategy_ret"], result["equity"])
    bh_perf = performance(result["xau_t1"], buyhold)

    print(f"k-NN Sharpe 3-head: K_MEM={K_MEM}, TEMP={TEMP}, K={k}, WINDOW={window}, TC={TC*100:.4f}%")
    print(f"Total OOS days: {len(result)}")
    print(f"Date range: {result.index.min().date()} to {result.index.max().date()}")
    print()
    print("=== k-NN Sharpe multi-head (walk-forward OOS) ===")
    for k_, v in strat_perf.items():
        print(f"  {k_}: {v:.4f}")
    print()
    print("=== Buy-and-hold XAU (same days) ===")
    for k_, v in bh_perf.items():
        print(f"  {k_}: {v:.4f}")
    print()

    result.to_csv(DATA / "multi_head_knn_sharpe_equity.csv")
    summary = {
        "k_mem": K_MEM,
        "temp": TEMP,
        "k": k,
        "window": window,
        "tc_per_trade": TC,
        "n_months": len(month_records),
        "n_days": int(len(result)),
        "strategy_metrics": strat_perf,
        "buyhold_metrics": bh_perf,
        "month_records": month_records,
        "note": "k-NN Sharpe weighting of atr_sizing, graph_knn_thb_xag, and vol_silver. Research only.",
    }
    (DATA / "multi_head_knn_sharpe_results.json").write_text(json.dumps(summary, indent=2))
    print("Saved: data/multi_head_knn_sharpe_equity.csv, data/multi_head_knn_sharpe_results.json")


if __name__ == "__main__":
    main()
