"""Equal-weight multi-head baseline for THB/XAU/XAG trading.

Runs three existing heads (ATR-sized THB+XAG, graph+k-NN THB+XAG,
volatility-targeted silver) and averages their signed positions.
This is the simplest multi-head ensemble for the new idea.

Usage:
    .venv/bin/python multi_head_experts_equal.py
"""
import json
import os
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=FutureWarning)

# Shared hyper-parameters across heads for a clean comparison
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

# Import the three head modules. They must live next to this file.
import trended_atr_sizing as atr
import trended_graph_knn_thb_xag as gkx
import trended_graph_knn_vol_silver as vks

ROOT = Path(__file__).parent
DATA = ROOT / "data"
TC = float(os.environ.get("TC", "0.0005"))
MAX_LEVERAGE = float(os.environ.get("MAX_LEVERAGE", "2.0"))


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


def month_positions(df, X_all, y_all, dates, head_name, head_module, month):
    """Return the per-day position vector for one head for one month."""
    month_map = pd.Series(dates).dt.to_period("M")
    month_mask = month_map == month
    month_dates = dates[month_mask]
    if len(month_dates) == 0:
        return np.array([])

    start = month_dates[0]
    train_end = start - pd.Timedelta(days=1)
    train_idx = np.array([i for i, d in enumerate(dates) if d < train_end]).astype(int)
    train_idx = train_idx[-int(os.environ.get("LOOKBACK", "252")):]

    raw_train = df[df.index < start].tail(int(os.environ.get("EDGE_LOOKBACK", "504")))
    p_value = head_module.granger_p(raw_train)
    edge_active = p_value <= float(os.environ.get("P_THRESHOLD", "0.01"))

    n_train_min = max(
        int(os.environ.get("WINDOW", "2")) + int(os.environ.get("K", "50")),
        63,
    )
    if len(train_idx) < n_train_min or not edge_active:
        return pd.Series(0.0, index=month_dates, name=head_name)

    X_train = X_all[train_idx]
    y_train = y_all[train_idx]
    scaler = head_module.StandardScaler().fit(X_train) if hasattr(head_module, "StandardScaler") else None
    # StandardScaler comes from sklearn and is already imported inside each head.
    from sklearn.preprocessing import StandardScaler as _StandardScaler
    scaler = _StandardScaler().fit(X_train)
    X_train_s = scaler.transform(X_train)

    train_pred = head_module.predict(X_train_s, y_train, X_train_s, int(os.environ.get("K", "50")), True)
    threshold = head_module.search_threshold(train_pred, y_train)

    test_idx = np.where(month_mask)[0]
    X_test = X_all[test_idx]
    X_test_s = scaler.transform(X_test)
    y_test = y_all[test_idx]
    y_pred = head_module.predict(X_train_s, y_train, X_test_s, int(os.environ.get("K", "50")), True)

    # Compute per-head position.
    positions = np.zeros(len(month_dates))
    for j, (d, yp, y) in enumerate(zip(month_dates, y_pred, y_test)):
        pos = 0.0
        if yp > threshold:
            pos = 1.0
        elif yp < -threshold:
            pos = -1.0

        # Apply head-specific sizing if the module exposes it.
        if head_name == "atr_sizing":
            xau_rets = raw_train["xau_ret"]
            atr = xau_rets.tail(int(os.environ.get("ATR_WINDOW", "14"))).abs().mean()
            daily_vol = atr * np.sqrt(252)
            size = min(float(os.environ.get("MAX_LEVERAGE", "2.0")), float(os.environ.get("TARGET_VOL", "0.20")) / daily_vol) if daily_vol > 0 else 0.0
            pos *= size
        elif head_name == "vol_silver":
            from sklearn.preprocessing import StandardScaler
            daily_target = float(os.environ.get("TARGET_VOL", "0.20")) / np.sqrt(252)
            realized_vol = y_train.std()
            size = min(float(os.environ.get("MAX_LEVERAGE", "2.0")), daily_target / realized_vol) if realized_vol > 0 and not np.isnan(realized_vol) else 0.0
            pos *= size
        else:
            # graph_knn_thb_xag uses unit size
            pass
        positions[j] = pos

    return pd.Series(positions, index=month_dates, name=head_name)


def main():
    df = load()

    # Build features for each head
    X_atr, dates_atr = atr.build_features(df, int(os.environ.get("WINDOW", "2")))
    X_gkx, dates_gkx = gkx.build_features(df, int(os.environ.get("WINDOW", "2")))
    X_vks, dates_vks = vks.build_features(df, int(os.environ.get("WINDOW", "2")))

    if not (len(dates_atr) == len(dates_gkx) == len(dates_vks)):
        print("Warning: heads have different date lengths", file=sys.stderr)
    dates = dates_atr
    y_all = df.loc[dates, "xau_t1"].values

    months = dates.to_period("M").unique()

    records = []
    prev_pos = 0.0
    equity = 1.0
    month_records = []

    for month in months:
        pos_atr = month_positions(df, X_atr, y_all, dates, "atr_sizing", atr, month)
        pos_gkx = month_positions(df, X_gkx, y_all, dates, "graph_knn_thb_xag", gkx, month)
        pos_vks = month_positions(df, X_vks, y_all, dates, "vol_silver", vks, month)

        # Align and equal-weight
        positions_df = pd.DataFrame({"atr": pos_atr, "gkx": pos_gkx, "vks": pos_vks})
        positions_df["final"] = positions_df.mean(axis=1)

        for d, row in positions_df.iterrows():
            final_pos = np.clip(row["final"], -MAX_LEVERAGE, MAX_LEVERAGE)
            y = df.loc[d, "xau_t1"]
            ret = final_pos * y - TC * abs(final_pos - prev_pos)
            prev_pos = final_pos
            equity *= np.exp(ret)
            records.append({
                "date": d,
                "position": float(final_pos),
                "atr_pos": float(row["atr"]),
                "gkx_pos": float(row["gkx"]),
                "vks_pos": float(row["vks"]),
                "xau_t1": float(y),
                "strategy_ret": float(ret),
                "equity": float(equity),
            })

        month_records.append({
            "month": str(month),
            "n_days": int(len(positions_df)),
        })

    result = pd.DataFrame(records).set_index("date").sort_index()
    buyhold = np.exp(result["xau_t1"].cumsum())
    strat_perf = performance(result["strategy_ret"], result["equity"])
    bh_perf = performance(result["xau_t1"], buyhold)

    print(f"Equal-weight 3-head: WINDOW={os.environ.get('WINDOW', '2')}, K={os.environ.get('K', '50')}, TC={float(os.environ['TC'])*100:.4f}%")
    print(f"Total OOS days: {len(result)}")
    print(f"Date range: {result.index.min().date()} to {result.index.max().date()}")
    print()
    print("=== Equal-weight multi-head (walk-forward OOS) ===")
    for k, v in strat_perf.items():
        print(f"  {k}: {v:.4f}")
    print()
    print("=== Buy-and-hold XAU (same days) ===")
    for k, v in bh_perf.items():
        print(f"  {k}: {v:.4f}")
    print()

    result.to_csv(DATA / "multi_head_equal_equity.csv")
    summary = {
        "window": int(os.environ.get("WINDOW", "2")),
        "k": int(os.environ.get("K", "50")),
        "tc_per_trade": float(os.environ["TC"]),
        "n_months": len(month_records),
        "n_days": int(len(result)),
        "strategy_metrics": strat_perf,
        "buyhold_metrics": bh_perf,
        "month_records": month_records,
        "note": "Equal-weight baseline of atr_sizing, graph_knn_thb_xag, and vol_silver. Research only.",
    }
    (DATA / "multi_head_equal_results.json").write_text(json.dumps(summary, indent=2))
    print("Saved: data/multi_head_equal_equity.csv, data/multi_head_equal_results.json")


if __name__ == "__main__":
    main()
