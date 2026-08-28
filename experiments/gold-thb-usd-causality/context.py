"""Context-vector builder for the multi-head expert system.

Builds a fixed-size numeric state vector per date from the aligned XAU/THB/XAG
returns. All features are causal (use only data up to and including the date).

Usage:
    from context import build_context_vectors, FEATURE_NAMES
    X, names = build_context_vectors(df, dates)
"""
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent
DATA = ROOT / "data"

FEATURE_NAMES = [
    "xau_sum2", "thb_sum2", "xag_sum2",
    "xau_sum5", "thb_sum5", "xag_sum5",
    "xau_sum10", "thb_sum10", "xag_sum10",
    "xau_vol5", "thb_vol5", "xag_vol5",
    "xau_vol20", "thb_vol20", "xag_vol20",
    "xau_rsi14", "thb_rsi14",
    "xau_bbz20", "thb_bbz20",
    "xau_thb_corr20", "xau_xag_corr20",
    "sma5_gt_sma20_xau",
    "ema5_gt_ema20_xau",
    "xau_dd_from_peak",
]


def _rsi(s: pd.Series, n: int = 14) -> pd.Series:
    """Wilder-style RSI, causal."""
    gains = s.clip(lower=0)
    losses = (-s).clip(lower=0)
    avg_gain = gains.ewm(alpha=1.0 / n, min_periods=n).mean()
    avg_loss = losses.ewm(alpha=1.0 / n, min_periods=n).mean()
    rs = avg_gain / (avg_loss + 1e-12)
    return 100.0 - 100.0 / (1.0 + rs)


def build_context_df(df: pd.DataFrame) -> pd.DataFrame:
    """Build a DataFrame of context vectors indexed by df.index."""
    c = pd.DataFrame(index=df.index)

    # Recent log-return sums
    for w in [2, 5, 10]:
        c[f"xau_sum{w}"] = df["xau_ret"].rolling(w, min_periods=1).sum()
        c[f"thb_sum{w}"] = df["thb_ret"].rolling(w, min_periods=1).sum()
        c[f"xag_sum{w}"] = df["xag_ret"].rolling(w, min_periods=1).sum()

    # Annualized realized volatilities
    for w in [5, 20]:
        c[f"xau_vol{w}"] = df["xau_ret"].rolling(w, min_periods=2).std() * np.sqrt(252)
        c[f"thb_vol{w}"] = df["thb_ret"].rolling(w, min_periods=2).std() * np.sqrt(252)
        c[f"xag_vol{w}"] = df["xag_ret"].rolling(w, min_periods=2).std() * np.sqrt(252)

    # RSI
    c["xau_rsi14"] = _rsi(df["xau_ret"], 14)
    c["thb_rsi14"] = _rsi(df["thb_ret"], 14)

    # Bollinger z-score (return vs 20-day SMA / 20-day std)
    sma20 = df["xau_ret"].rolling(20, min_periods=5).mean()
    std20 = df["xau_ret"].rolling(20, min_periods=5).std()
    c["xau_bbz20"] = (df["xau_ret"] - sma20) / (std20 + 1e-12)
    sma20 = df["thb_ret"].rolling(20, min_periods=5).mean()
    std20 = df["thb_ret"].rolling(20, min_periods=5).std()
    c["thb_bbz20"] = (df["thb_ret"] - sma20) / (std20 + 1e-12)

    # Rolling correlations
    c["xau_thb_corr20"] = df["xau_ret"].rolling(20, min_periods=5).corr(df["thb_ret"])
    c["xau_xag_corr20"] = df["xau_ret"].rolling(20, min_periods=5).corr(df["xag_ret"])

    # SMA/EMA crossovers
    c["sma5_gt_sma20_xau"] = (
        df["xau_ret"].rolling(5, min_periods=1).mean() >
        df["xau_ret"].rolling(20, min_periods=1).mean()
    ).astype(float)
    c["ema5_gt_ema20_xau"] = (
        df["xau_ret"].ewm(span=5, min_periods=1).mean() >
        df["xau_ret"].ewm(span=20, min_periods=1).mean()
    ).astype(float)

    # XAU drawdown from peak
    price = np.exp(df["xau_ret"].cumsum())
    peak = price.cummax()
    c["xau_dd_from_peak"] = price / peak - 1.0

    # Fill early NaNs with 0 (cold-start regime)
    return c.fillna(0.0)


def build_context_vectors(df: pd.DataFrame, dates: pd.DatetimeIndex):
    """Return (X, feature_names) for the requested dates."""
    ctx = build_context_df(df)
    ctx = ctx.loc[dates, FEATURE_NAMES]
    return ctx.values.astype(np.float64), FEATURE_NAMES


if __name__ == "__main__":
    import sys
    if not (DATA / "aligned_silver.csv").exists():
        print("Run prepare_silver.py first", file=sys.stderr)
        raise SystemExit(1)
    df = pd.read_csv(DATA / "aligned_silver.csv", parse_dates=["date"])
    df = df.sort_values("date").dropna().set_index("date")
    logdf = np.log(df)
    rets = logdf.diff().dropna()
    rets.columns = ["xau_ret", "thb_ret", "xag_ret"]
    ctx = build_context_df(rets)
    out = DATA / "context_vectors.csv"
    ctx.to_csv(out)
    print(f"Saved {out} ({ctx.shape[0]} rows, {ctx.shape[1]} features)")
