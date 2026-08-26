"""Merge XAU/THB, XAG/silver, oil, and USD/EUR into a single aligned CSV.

Reads data/aligned_silver.csv, data/aligned_oil.csv, and data/aligned_usd.csv,
joins on date, and writes data/aligned_silver_multi.csv with columns
xau, thb, xag, wti, brent, usd. Research only.
"""
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).parent
DATA = ROOT / "data"


def main():
    silver = pd.read_csv(DATA / "aligned_silver.csv", parse_dates=["date"]).sort_values("date").dropna()
    oil = pd.read_csv(DATA / "aligned_oil.csv", parse_dates=["date"]).sort_values("date").dropna()[["date", "oil", "brent"]]
    usd = pd.read_csv(DATA / "aligned_usd.csv", parse_dates=["date"]).sort_values("date").dropna()[["date", "usd"]]

    out = silver.merge(oil, on="date", how="inner").merge(usd, on="date", how="inner")
    out = out.dropna()
    out.to_csv(DATA / "aligned_silver_multi.csv", index=False)
    print(f"Saved data/aligned_silver_multi.csv: {len(out)} rows from {out['date'].min().date()} to {out['date'].max().date()}")


if __name__ == "__main__":
    main()
