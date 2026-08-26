"""Gold/THB/USD causality analysis with USD/EUR proxy.

Run with the local venv:
    experiments/gold-thb-usd-causality/.venv/bin/python experiments/gold-thb-usd-causality/analyze.py
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import adfuller, grangercausalitytests, coint
from statsmodels.tsa.api import VAR

ROOT = Path(__file__).parent
DATA = ROOT / "data"


def make_json_safe(obj):
    """Recursively convert numpy/scipy types to plain Python types."""
    if isinstance(obj, dict):
        return {k: make_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [make_json_safe(v) for v in obj]
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    return obj


def main():
    # Load raw CSVs
    xau = pd.read_csv(DATA / "xau_usd.csv", parse_dates=["date"])
    thb = pd.read_csv(DATA / "usd_thb.csv", parse_dates=["date"])
    eur = pd.read_csv(DATA / "usd_eur.csv", parse_dates=["date"])

    # Use close prices, rename for clarity
    xau = xau.rename(columns={"close": "xau"})[["date", "xau"]]
    thb = thb.rename(columns={"close": "thb"})[["date", "thb"]]
    eur = eur.rename(columns={"close": "usd"})[["date", "usd"]]

    # Inner join on common dates, sort ascending
    df = (
        pd.merge(xau, thb, on="date", how="inner")
        .merge(eur, on="date", how="inner")
        .sort_values("date")
        .drop_duplicates("date")
    )
    df.set_index("date", inplace=True)

    print(f"Common aligned observations: {len(df)}")
    print(f"Date range: {df.index.min().date()} to {df.index.max().date()}")
    print(df.describe().round(4).to_string())
    print()

    # Save aligned levels
    df.to_csv(DATA / "aligned.csv")

    # Log returns for stationarity
    logdf = np.log(df)
    rets = logdf.diff().dropna()
    rets.columns = ["xau_ret", "thb_ret", "usd_ret"]
    rets.to_csv(DATA / "returns.csv")

    # Stationarity tests (ADF) on log levels and returns
    def adf_summary(series, name):
        adf = adfuller(series.dropna(), autolag="aic")
        return {
            "variable": name,
            "adf_statistic": round(float(adf[0]), 4),
            "p_value": round(float(adf[1]), 4),
            "is_stationary_5pct": bool(adf[0] < adf[4]["5%"]),
        }

    adf_results = [
        adf_summary(logdf[c], f"log {c}/usd" if c != "usd" else "log usd/eur")
        for c in ["xau", "thb", "usd"]
    ]
    adf_results += [
        adf_summary(rets[c], f"{c} return")
        for c in ["xau_ret", "thb_ret", "usd_ret"]
    ]

    print("=== ADF stationarity tests ===")
    for r in adf_results:
        print(r)
    print()

    # Cointegration (Engle-Granger) on log levels
    coint_results = []
    for a, b in [("xau", "thb"), ("xau", "usd"), ("thb", "usd")]:
        t, p, cvals = coint(logdf[a], logdf[b])
        coint_results.append({
            "pair": f"{a}-{b}",
            "t_statistic": round(float(t), 4),
            "p_value": round(float(p), 4),
            "is_cointegrated_5pct": bool(t < cvals[2]),
        })

    print("=== Cointegration tests (Engle-Granger) ===")
    for r in coint_results:
        print(r)
    print()

    # Cross-correlation of returns
    lags = list(range(-10, 11))
    ccf = [rets["xau_ret"].corr(rets["thb_ret"].shift(l)) for l in lags]
    ccf_series = pd.Series(ccf, index=lags)
    max_idx = ccf_series.abs().idxmax()
    print("=== Cross-correlation of returns (xau vs thb) ===")
    print(ccf_series.round(4).to_string())
    print(f"Strongest lag: {max_idx} (corr = {ccf_series[max_idx]:.4f})")
    print()

    # Bivariate Granger causality on returns (baseline)
    maxlag = 5
    g_results = {}
    for cause, effect in [("xau_ret", "thb_ret"), ("thb_ret", "xau_ret")]:
        test_data = rets[[effect, cause]].dropna()
        gc = grangercausalitytests(test_data, maxlag=maxlag, verbose=False)
        g_results[f"{cause}_causes_{effect}"] = {
            str(lag): {
                "ftest_pvalue": round(float(gc[lag][0]["ssr_ftest"][1]), 4),
                "chi2_pvalue": round(float(gc[lag][0]["ssr_chi2test"][1]), 4),
            }
            for lag in range(1, maxlag + 1)
        }

    # VAR on trivariate returns, USD as a control/proxy
    var_df = rets[["xau_ret", "thb_ret", "usd_ret"]].dropna()
    var_model = VAR(var_df)
    var_results = var_model.fit(maxlags=5, ic="aic")

    print(f"=== VAR selected lag: {var_results.k_ar} ===")
    print(var_results.summary())
    print()

    # Causality tests inside the trivariate VAR (F-tests)
    var_causality = {}
    for cause in ["thb_ret", "usd_ret"]:
        test = var_results.test_causality(caused="xau_ret", causing=cause, kind="f")
        var_causality[f"{cause}_causes_xau_ret"] = {
            "f_statistic": round(float(test.test_statistic), 4),
            "p_value": round(float(test.pvalue), 4),
        }
    for cause in ["xau_ret", "usd_ret"]:
        test = var_results.test_causality(caused="thb_ret", causing=cause, kind="f")
        var_causality[f"{cause}_causes_thb_ret"] = {
            "f_statistic": round(float(test.test_statistic), 4),
            "p_value": round(float(test.pvalue), 4),
        }

    print("=== VAR Granger causality tests ===")
    for name, vals in var_causality.items():
        print(f"  {name}: F = {vals['f_statistic']}, p = {vals['p_value']}")
    print()

    # Impulse response: response of xau to orthogonal shocks in thb and usd
    irf = var_results.irf(10)
    # var_names order is xau, thb, usd
    name_to_idx = {name: i for i, name in enumerate(var_df.columns)}
    irf_values = {}
    for shock in ["thb_ret", "usd_ret"]:
        s = name_to_idx[shock]
        r = name_to_idx["xau_ret"]
        irf_values[f"xau_response_to_{shock}"] = [
            round(float(irf.irfs[step, r, s]), 6) for step in range(10)
        ]

    print("=== IRF: response of xau_ret to 1-unit shocks ===")
    for name, vals in irf_values.items():
        print(f"  {name}: {vals}")
    print()

    # Save machine-readable summary
    summary = {
        "observations": int(len(df)),
        "date_range": [str(df.index.min().date()), str(df.index.max().date())],
        "adf_tests": adf_results,
        "cointegration": coint_results,
        "cross_correlation_peak": {
            "lag": int(max_idx),
            "correlation": round(float(ccf_series[max_idx]), 4),
            "all_lags": {str(k): round(float(v), 4) for k, v in ccf_series.items()},
        },
        "granger_causality_bivariate": g_results,
        "var_granger_causality": make_json_safe(var_causality),
        "impulse_response_xau": make_json_safe(irf_values),
    }
    (DATA / "results.json").write_text(json.dumps(make_json_safe(summary), indent=2))
    print("Saved: data/aligned.csv, data/returns.csv, data/results.json")


if __name__ == "__main__":
    main()
