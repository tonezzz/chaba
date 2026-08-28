"""k-NN Sharpe multi-head weighting with five heads.

Heads: ATR-sized THB+XAG, graph+k-NN THB+XAG, vol-sized silver,
RSI filter, and SMA THB overlay. The same context/memory machinery is used;
only the head panel is larger.

Usage:
    K_MEM=50 TEMP=1.0 .venv/bin/python multi_head_knn_sharpe_5h.py
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
os.environ.setdefault("RSI_WINDOW", "14")
os.environ.setdefault("OVERSOLD", "30")
os.environ.setdefault("OVERBOUGHT", "70")
os.environ.setdefault("SHORT", "5")
os.environ.setdefault("LONG", "20")
os.environ.setdefault("K_MEM", "50")
os.environ.setdefault("TEMP", "1.0")

import trended_atr_sizing as atr
import trended_graph_knn_thb_xag as gkx
import trended_graph_knn_vol_silver as vol
import trended_rsi_filter as rsi
import trended_sma_overlay as sma

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


def month_head_positions(df, X_all, y_all, dates, head_name, head_module, month,
                         window, k, lookback, edge_lookback, p_threshold):
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

    # Head-specific monthly state
    if head_name == "rsi":
        xau_rets = raw_train["xau_ret"]
        gains = xau_rets.clip(lower=0)
        losses = (-xau_rets).clip(lower=0)
        avg_gain = gains.tail(int(os.environ["RSI_WINDOW"])).mean()
        avg_loss = losses.tail(int(os.environ["RSI_WINDOW"])).mean()
        rsi_val = 100.0 if avg_loss == 0 else 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    elif head_name == "sma":
        thb_train = raw_train["thb_ret"]
        sma_short = thb_train.tail(int(os.environ["SHORT"])).mean()
        sma_long = thb_train.tail(int(os.environ["LONG"])).mean()
        sma_up = bool(sma_short > sma_long)

    positions = np.zeros(len(month_dates))
    xau_rets = raw_train["xau_ret"]
    for j, (yp, y) in enumerate(zip(y_pred, y_test)):
        pos = 0.0
        if head_name == "rsi":
            if yp > threshold and rsi_val < float(os.environ["OVERBOUGHT"]):
                pos = 1.0
            elif yp < -threshold and rsi_val > float(os.environ["OVERSOLD"]):
                pos = -1.0
        elif head_name == "sma":
            if yp > threshold and sma_up:
                pos = 1.0
            elif yp < -threshold and not sma_up:
                pos = -1.0
        else:
            if yp > threshold:
                pos = 1.0
            elif yp < -threshold:
                pos = -1.0

        if head_name == "atr" and pos != 0.0:
            atr = xau_rets.tail(int(os.environ["ATR_WINDOW"])).abs().mean()
            daily_vol = atr * np.sqrt(252)
            size = min(MAX_LEVERAGE, float(os.environ["TARGET_VOL"]) / daily_vol) if daily_vol > 0 else 0.0
            pos *= size
        elif head_name == "vol" and pos != 0.0:
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

    head_specs = [
        ("atr", atr, atr.build_features(df, window)),
        ("gkx", gkx, gkx.build_features(df, window)),
        ("vol", vol, vol.build_features(df, window)),
        ("rsi", rsi, rsi.build_features(df, window)),
        ("sma", sma, sma.build_features(df, window)),
    ]
    n_heads = len(head_specs)

    dates = head_specs[0][2][1]
    y_all = df.loc[dates, "xau_t1"].values

    context_vectors, _ = build_context_vectors(df, dates)

    months = dates.to_period("M").unique()
    memory = Memory(k=K_MEM)

    records = []
    prev_pos = 0.0
    equity = 1.0
    month_records = []

    for m_idx, month in enumerate(months):
        # Compute per-head positions for the month
        head_positions = []
        for h_name, h_module, (X_all, _) in head_specs:
            pos = month_head_positions(df, X_all, y_all, dates, h_name, h_module,
                                       month, window, k, lookback, edge_lookback, p_threshold)
            head_positions.append(pos)

        month_map = pd.Series(dates).dt.to_period("M")
        test_idx = np.where(month_map == month)[0]

        if m_idx > 0 and len(memory) >= K_MEM:
            memory.fit()

        month_contexts = []
        month_head_returns = []

        for j, day_idx in enumerate(test_idx):
            y = y_all[day_idx]
            hpos = np.array([hp[j] for hp in head_positions])
            ctx = context_vectors[day_idx]

            neighbors = memory.query(ctx) if len(memory) >= K_MEM else None
            if neighbors is not None and len(neighbors) >= K_MEM:
                local_sharpe = np.zeros(n_heads)
                for h in range(n_heads):
                    rets = neighbors[:, h]
                    if rets.std() > 0:
                        local_sharpe[h] = rets.mean() / rets.std() * np.sqrt(252)
                weights = softmax(local_sharpe, TEMP)
            else:
                weights = np.ones(n_heads) / n_heads

            final_pos = np.dot(weights, hpos)
            final_pos = np.clip(final_pos, -MAX_LEVERAGE, MAX_LEVERAGE)
            ret = final_pos * y - TC * abs(final_pos - prev_pos)
            prev_pos = final_pos
            equity *= np.exp(ret)

            gross_head_returns = hpos * y
            month_contexts.append(ctx)
            month_head_returns.append(gross_head_returns)

            rec = {
                "date": dates[day_idx],
                "position": float(final_pos),
                "xau_t1": float(y),
                "strategy_ret": float(ret),
                "equity": float(equity),
            }
            for h in range(n_heads):
                rec[f"weight_{head_specs[h][0]}"] = float(weights[h])
                rec[f"pos_{head_specs[h][0]}"] = float(hpos[h])
            records.append(rec)

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

    print(f"k-NN Sharpe 5-head: K_MEM={K_MEM}, TEMP={TEMP}, K={k}, WINDOW={window}, TC={TC*100:.4f}%")
    print(f"Total OOS days: {len(result)}")
    print(f"Date range: {result.index.min().date()} to {result.index.max().date()}")
    print()
    print("=== k-NN Sharpe 5-head (walk-forward OOS) ===")
    for k_, v in strat_perf.items():
        print(f"  {k_}: {v:.4f}")
    print()
    print("=== Buy-and-hold XAU (same days) ===")
    for k_, v in bh_perf.items():
        print(f"  {k_}: {v:.4f}")
    print()

    result.to_csv(DATA / "multi_head_knn_sharpe_5h_equity.csv")
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
        "note": "k-NN Sharpe weighting of 5 heads: atr, gkx, vol, rsi, sma. Research only.",
    }
    (DATA / "multi_head_knn_sharpe_5h_results.json").write_text(json.dumps(summary, indent=2))
    print("Saved: data/multi_head_knn_sharpe_5h_equity.csv, data/multi_head_knn_sharpe_5h_results.json")


if __name__ == "__main__":
    main()
