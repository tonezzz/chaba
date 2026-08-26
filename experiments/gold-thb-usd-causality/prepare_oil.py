"""Align WTI and Brent crude oil prices with the existing aligned.csv date range.

Reads data/wti.csv and data/brent.csv, forward-fills missing days and aligns to
data/aligned.csv. Writes data/aligned_oil.csv with columns date, xau, thb, oil, brent.
The `oil` column is WTI, matching trended_oil.py. Research only.
"""
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).parent
DATA = ROOT / "data"


def load_oil(path):
    df = pd.read_csv(path)
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.sort_values("timestamp").set_index("timestamp").dropna()
    return df[~df.index.duplicated(keep="first")]["value"]


def main():
    if not (DATA / "wti.csv").exists() or not (DATA / "brent.csv").exists():
        print("data/wti.csv and data/brent.csv are required. Run the fetch step first.", file=__import__("sys").stderr)
        raise SystemExit(1)

    wti = load_oil(DATA / "wti.csv")
    brent = load_oil(DATA / "brent.csv")

    aligned = pd.read_csv(DATA / "aligned.csv", parse_dates=["date"]).sort_values("date").dropna()
    aligned = aligned[["date", "xau", "thb"]]
    dates = aligned["date"]

    # Forward-fill to the aligned dates; backfill only if a series starts after the first date
    wti_aligned = wti.reindex(dates, method="ffill").bfill()
    brent_aligned = brent.reindex(dates, method="ffill").bfill()

    out = aligned.copy()
    out["oil"] = wti_aligned.values
    out["brent"] = brent_aligned.values
    out = out.dropna()
    out.to_csv(DATA / "aligned_oil.csv", index=False)
    print(f"Saved data/aligned_oil.csv: {len(out)} rows from {out['date'].min().date()} to {out['date'].max().date()}")


if __name__ == "__main__":
    main()
