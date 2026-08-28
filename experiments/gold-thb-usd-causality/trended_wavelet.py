"""Walk-forward wavelet trend strategy.

For each month, compute causal complex Morlet wavelet transforms of USD/THB
returns at several scales. Search the training window to find the scale and
component (real or imaginary part) whose sign best predicts the next XAU
return. Trade the sign of the selected wavelet component when it is outside a
threshold.

This is a simplified wavelet implementation; full wavelet coherence with XAU
could be added later.

Research only, not a live trading strategy.

Usage:
    SCALES=4,8,16 .venv/bin/python trended_wavelet.py
"""
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.signal import lfilter

ROOT = Path(__file__).parent
DATA = ROOT / "data"
LOOKBACK = int(os.environ.get("LOOKBACK", "252"))
SCALES = [int(x) for x in os.environ.get("SCALES", "4,8,16,32").split(",")]
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


def morlet_filter(scale, omega0=6.0):
    """Causal complex Morlet FIR filter of length 8*scale."""
    M = max(8 * scale, 4)
    t = np.arange(M) - M // 2
    w = np.exp(1j * omega0 * t / scale) * np.exp(-(t ** 2) / (2.0 * (scale / 2.0) ** 2))
    w = w / np.sqrt(np.sum(np.abs(w) ** 2))
    return w


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


def search_threshold(sig, y, upper=None):
    best = {"sharpe": -np.inf, "threshold": 0.0}
    if upper is None:
        upper = np.percentile(np.abs(sig), 90)
    for c in np.linspace(0.0, upper, 21):
        # THB-like positive -> short XAU; negative -> long XAU
        pos = np.where(sig > c, -1.0, np.where(sig < -c, 1.0, 0.0))
        rets = pos * y
        if rets.std() == 0:
            continue
        sharpe = rets.mean() / rets.std() * np.sqrt(252)
        if sharpe > best["sharpe"]:
            best = {"sharpe": sharpe, "threshold": float(c)}
    return best["threshold"]


def main():
    df = load()
    thb = df["thb_ret"].values
    xau = df["xau_t1"].values
    dates = df.index
    n = len(df)

    # Precompute wavelet transforms for all scales
    wavelets = {}
    for s in SCALES:
        w = morlet_filter(s)
        wf = lfilter(w, 1.0, thb)
        wavelets[s] = {
            "real": np.real(wf),
            "imag": np.imag(wf),
            "M": len(w),
        }

    month_map = dates.to_period("M")
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

        train_start = max(0, p0 - LOOKBACK)
        train_pos = np.arange(train_start, p0)

        if len(train_pos) < 64:
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

        # grid search on training data
        best = {"sharpe": -np.inf, "scale": SCALES[0], "comp": "real", "threshold": 0.0}
        for s in SCALES:
            for comp in ("real", "imag"):
                sig = wavelets[s][comp][train_pos]
                valid = ~np.isnan(sig) & ~np.isnan(xau[train_pos])
                if valid.sum() < 63:
                    continue
                th = search_threshold(sig[valid], xau[train_pos][valid])
                pos = np.where(sig[valid] > th, -1.0, np.where(sig[valid] < -th, 1.0, 0.0))
                rets = pos * xau[train_pos][valid]
                if rets.std() == 0:
                    continue
                sharpe = rets.mean() / rets.std() * np.sqrt(252)
                if sharpe > best["sharpe"]:
                    best = {"sharpe": sharpe, "scale": s, "comp": comp, "threshold": th}

        sig_test = wavelets[best["scale"]][best["comp"]]

        for d in month_dates:
            p = pos_map[d]
            pos = 0.0
            s_t = sig_test[p]
            if not np.isnan(s_t):
                if s_t > best["threshold"]:
                    pos = -1.0
                elif s_t < -best["threshold"]:
                    pos = 1.0
            y = xau[p]
            ret = pos * y - TC * abs(pos - prev_pos)
            prev_pos = pos
            equity *= np.exp(ret)
            records.append({
                "date": d,
                "position": pos,
                "y_pred": float(-s_t) if pos != 0 else 0.0,
                "xau_t1": float(y),
                "strategy_ret": float(ret),
                "equity": float(equity),
            })

        month_records.append({
            "month": str(month),
            "scale": int(best["scale"]),
            "component": best["comp"],
            "threshold": float(best["threshold"]),
            "n_train": int(len(train_pos)),
            "n_test": int(len(month_dates)),
        })

    result = pd.DataFrame(records).set_index("date").sort_index()
    buyhold = np.exp(result["xau_t1"].cumsum())
    strat_perf = performance(result["strategy_ret"], result["equity"])
    bh_perf = performance(result["xau_t1"], buyhold)

    print(f"Wavelet: SCALES={','.join(str(s) for s in SCALES)}, LOOKBACK={LOOKBACK}, TC={TC*100:.4f}%")
    print(f"Total OOS days: {len(result)}")
    print(f"Date range: {result.index.min().date()} to {result.index.max().date()}")
    print()

    print("=== Wavelet trend (walk-forward OOS) ===")
    for k, v in strat_perf.items():
        print(f"  {k}: {v:.4f}")
    print()

    print("=== Buy-and-hold XAU (same days) ===")
    for k, v in bh_perf.items():
        print(f"  {k}: {v:.4f}")
    print()

    result.to_csv(DATA / "trended_wavelet_equity.csv")
    summary = {
        "scales": SCALES,
        "lookback_days": LOOKBACK,
        "tc_per_trade": TC,
        "n_months": len(month_records),
        "n_days": int(len(result)),
        "strategy_metrics": strat_perf,
        "buyhold_metrics": bh_perf,
        "monthly_thresholds": month_records,
        "note": "Causal complex Morlet CWT on THB returns. Research only.",
    }
    (DATA / "trended_wavelet_results.json").write_text(json.dumps(summary, indent=2))
    print("Saved: data/trended_wavelet_equity.csv, data/trended_wavelet_results.json")


if __name__ == "__main__":
    main()
