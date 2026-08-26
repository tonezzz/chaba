"""Walk-forward regime-switching VAR strategy.

At the start of each test month:
1. Compute a rolling THB volatility for the training window and split it at the
   median into a low-vol and a high-vol regime.
2. Fit a separate VAR on the training days in each regime.
3. For each test day, determine the current regime from recent THB volatility and
   forecast the next XAU return with the corresponding VAR.
4. Trade the sign of the forecast when its magnitude exceeds a threshold.

Research only, not a live trading strategy.

Usage:
    VAR_LAGS=2 REGIME_WINDOW=10 .venv/bin/python trended_regime_var.py
"""
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from statsmodels.tsa.api import VAR

ROOT = Path(__file__).parent
DATA = ROOT / "data"
LOOKBACK = int(os.environ.get("LOOKBACK", "252"))
VAR_LAGS = int(os.environ.get("VAR_LAGS", "2"))
REGIME_WINDOW = int(os.environ.get("REGIME_WINDOW", "10"))
TC = float(os.environ.get("TC", "0.0005"))


def load():
    if not (DATA / "aligned.csv").exists():
        print("Run analyze.py first to generate data/aligned.csv", file=sys.stderr)
        raise SystemExit(1)
    df = pd.read_csv(DATA / "aligned.csv", parse_dates=["date"])
    df = df.sort_values("date").dropna()
    df.set_index("date", inplace=True)
    logdf = np.log(df)
    df["thb_ret"] = logdf["thb"].diff()
    df["xau_ret"] = logdf["xau"].diff()
    df["xau_t1"] = logdf["xau"].shift(-1) - logdf["xau"]
    return df.dropna()


def compute_regime_vol(thb, window):
    s = pd.Series(thb)
    vol = s.rolling(window).std().abs().values
    return vol


def search_threshold(y_pred, y_true):
    best = {"sharpe": -np.inf, "threshold": 0.0}
    upper = np.percentile(np.abs(y_pred), 90)
    for c in np.linspace(0.0, upper, 21):
        signal = np.where(y_pred > c, 1.0, np.where(y_pred < -c, -1.0, 0.0))
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


def fit_var(df, endog_cols, maxlags):
    try:
        m = VAR(df[endog_cols])
        res = m.fit(maxlags=maxlags, trend="n")
        return res
    except Exception as e:
        return None


def main():
    df = load()
    thb = df["thb_ret"].values
    xau = df["xau_t1"].values
    dates = df.index
    n = len(df)

    # Precompute THB volatility for the whole series
    vol = compute_regime_vol(thb, REGIME_WINDOW)

    month_map = pd.Series(dates).dt.to_period("M")
    months = dates.to_period("M").unique()
    pos_map = {d: i for i, d in enumerate(dates)}

    records = []
    prev_pos = 0.0
    equity = 1.0
    month_records = []

    for month in months:
        month_dates = dates[month_map == month]
        if len(month_dates) == 0:
            continue
        p0 = pos_map[month_dates[0]]

        # training window
        train_start = max(0, p0 - LOOKBACK)
        train_pos = np.arange(train_start, p0)

        if len(train_pos) < max(VAR_LAGS, REGIME_WINDOW) + 20:
            for d in month_dates:
                records.append({
                    "date": d,
                    "position": 0.0,
                    "y_pred": 0.0,
                    "xau_t1": xau[pos_map[d]],
                    "strategy_ret": 0.0,
                    "equity": equity,
                })
            continue

        train_vol = vol[train_pos]
        train_thb = thb[train_pos]
        train_xau = xau[train_pos]
        train_xr = df["xau_ret"].values[train_pos]
        median_vol = np.nanmedian(train_vol)

        # low- and high-vol training data frames
        low_idx = train_vol <= median_vol
        high_idx = ~low_idx
        low_idx[0] = False
        high_idx[0] = False

        df_low = pd.DataFrame({"xau_ret": train_xr[low_idx], "thb_ret": train_thb[low_idx]})
        df_high = pd.DataFrame({"xau_ret": train_xr[high_idx], "thb_ret": train_thb[high_idx]})

        var_low = fit_var(df_low, ["xau_ret", "thb_ret"], VAR_LAGS)
        var_high = fit_var(df_high, ["xau_ret", "thb_ret"], VAR_LAGS)

        # in-sample forecasts for threshold search
        y_pred_train = np.full(len(train_pos), np.nan)
        for j, p in enumerate(train_pos):
            if p < VAR_LAGS:
                continue
            if np.isnan(vol[p]):
                continue
            var = var_low if vol[p] <= median_vol else var_high
            if var is None:
                continue
            y = pd.DataFrame({
                "xau_ret": df["xau_ret"].values[p - VAR_LAGS:p],
                "thb_ret": thb[p - VAR_LAGS:p],
            })
            try:
                f = var.forecast(y.values, steps=1)
                y_pred_train[j] = f[0, 0]
            except Exception:
                pass

        valid = ~np.isnan(y_pred_train)
        if valid.sum() < 63:
            threshold = 0.0
        else:
            threshold = search_threshold(y_pred_train[valid], train_xau[valid])

        # out-of-sample
        for d in month_dates:
            p = pos_map[d]
            yp = 0.0
            if p >= VAR_LAGS and not np.isnan(vol[p]) and p < n:
                var = var_low if vol[p] <= median_vol else var_high
                if var is not None:
                    y = pd.DataFrame({
                        "xau_ret": df["xau_ret"].values[p - VAR_LAGS:p],
                        "thb_ret": thb[p - VAR_LAGS:p],
                    })
                    try:
                        f = var.forecast(y.values, steps=1)
                        yp = float(f[0, 0])
                    except Exception:
                        yp = 0.0

            pos = 0.0
            if yp > threshold:
                pos = 1.0
            elif yp < -threshold:
                pos = -1.0
            y = xau[p]
            ret = pos * y - TC * abs(pos - prev_pos)
            prev_pos = pos
            equity *= np.exp(ret)
            records.append({
                "date": d,
                "position": pos,
                "y_pred": float(yp),
                "xau_t1": float(y),
                "strategy_ret": float(ret),
                "equity": float(equity),
            })

        month_records.append({
            "month": str(month),
            "threshold": threshold,
            "n_train": int(len(train_pos)),
            "n_test": int(len(month_dates)),
        })

    result = pd.DataFrame(records).set_index("date").sort_index()
    buyhold = np.exp(result["xau_t1"].cumsum())
    strat_perf = performance(result["strategy_ret"], result["equity"])
    bh_perf = performance(result["xau_t1"], buyhold)

    print(f"Regime-Switching VAR: VAR_LAGS={VAR_LAGS}, REGIME_WINDOW={REGIME_WINDOW}, LOOKBACK={LOOKBACK}, TC={TC*100:.4f}%")
    print(f"Total OOS days: {len(result)}")
    print(f"Date range: {result.index.min().date()} to {result.index.max().date()}")
    print()

    print("=== Regime-switching VAR (walk-forward OOS) ===")
    for k, v in strat_perf.items():
        print(f"  {k}: {v:.4f}")
    print()

    print("=== Buy-and-hold XAU (same days) ===")
    for k, v in bh_perf.items():
        print(f"  {k}: {v:.4f}")
    print()

    result.to_csv(DATA / "trended_regime_var_equity.csv")
    summary = {
        "var_lags": VAR_LAGS,
        "regime_window": REGIME_WINDOW,
        "lookback_days": LOOKBACK,
        "tc_per_trade": TC,
        "n_months": len(month_records),
        "n_days": int(len(result)),
        "strategy_metrics": strat_perf,
        "buyhold_metrics": bh_perf,
        "monthly_thresholds": month_records,
        "note": "Regime-switching VAR with low/high THB volatility. Research only.",
    }
    (DATA / "trended_regime_var_results.json").write_text(json.dumps(summary, indent=2))
    print("Saved: data/trended_regime_var_equity.csv, data/trended_regime_var_results.json")


if __name__ == "__main__":
    main()
