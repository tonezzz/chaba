"""Gold/THB/USD causality analysis.

Run with the local venv:
    experiments/gold-thb-usd-causality/.venv/bin/python experiments/gold-thb-usd-causality/analyze.py
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import adfuller, grangercausalitytests

ROOT = Path(__file__).parent
DATA = ROOT / "data"


def main():
    # Load raw CSVs
    xau = pd.read_csv(DATA / "xau_usd.csv", parse_dates=["date"])
    thb = pd.read_csv(DATA / "usd_thb.csv", parse_dates=["date"])

    # Use close prices, rename for clarity
    xau = xau.rename(columns={"close": "xau"})[["date", "xau"]]
    thb = thb.rename(columns={"close": "thb"})[["date", "thb"]]

    # Inner join on common dates, sort ascending
    df = pd.merge(xau, thb, on="date", how="inner").sort_values("date").drop_duplicates("date")
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
    rets.columns = ["xau_ret", "thb_ret"]
    rets.to_csv(DATA / "returns.csv")

    # Stationarity tests (ADF) on log levels and returns
    def adf_summary(series, name):
        adf = adfuller(series.dropna(), autolag="aic")
        return {
            "variable": name,
            "adf_statistic": round(adf[0], 4),
            "p_value": round(adf[1], 4),
            "is_stationary_5pct": bool(adf[0] < adf[4]["5%"]),
        }

    adf_results = [
        adf_summary(logdf["xau"], "log xau/usd"),
        adf_summary(logdf["thb"], "log usd/thb"),
        adf_summary(rets["xau_ret"], "xau return"),
        adf_summary(rets["thb_ret"], "thb return"),
    ]

    print("=== ADF stationarity tests ===")
    for r in adf_results:
        print(r)
    print()

    # Cross-correlation of returns at lags
    lags = list(range(-10, 11))
    ccf = [rets["xau_ret"].corr(rets["thb_ret"].shift(l)) for l in lags]
    ccf_series = pd.Series(ccf, index=lags)
    max_idx = ccf_series.abs().idxmax()
    print("=== Cross-correlation of returns (xau vs thb) ===")
    print(ccf_series.round(4).to_string())
    print(f"Strongest lag: {max_idx} (corr = {ccf_series[max_idx]:.4f})")
    print()

    # Granger causality on returns: both directions
    maxlag = 5
    g_results = {}
    for cause, effect in [("xau_ret", "thb_ret"), ("thb_ret", "xau_ret")]:
        test_data = rets[[effect, cause]].dropna()
        gc = grangercausalitytests(test_data, maxlag=maxlag, verbose=False)
        g_results[f"{cause}_causes_{effect}"] = {
            str(lag): {
                "ftest_pvalue": round(gc[lag][0]["ssr_ftest"][1], 4),
                "chi2_pvalue": round(gc[lag][0]["ssr_chi2test"][1], 4),
            }
            for lag in range(1, maxlag + 1)
        }

    print("=== Granger causality p-values (returns) ===")
    for name, lags in g_results.items():
        print(f"\n{name}:")
        for lag, pvals in lags.items():
            print(f"  lag {lag}: F-test p = {pvals['ftest_pvalue']}, chi2 p = {pvals['chi2_pvalue']}")
    print()

    # Save machine-readable summary
    summary = {
        "observations": int(len(df)),
        "date_range": [str(df.index.min().date()), str(df.index.max().date())],
        "adf_tests": adf_results,
        "cross_correlation_peak": {
            "lag": int(max_idx),
            "correlation": round(float(ccf_series[max_idx]), 4),
            "all_lags": {str(k): round(float(v), 4) for k, v in ccf_series.items()},
        },
        "granger_causality": g_results,
    }
    (DATA / "results.json").write_text(json.dumps(summary, indent=2))
    print("Saved: data/aligned.csv, data/returns.csv, data/results.json")


if __name__ == "__main__":
    main()
