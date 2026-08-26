"""Align USD/EUR with the existing XAU/THB aligned.csv date range.

Reads data/usd_eur.csv, forward-fills missing days and aligns to
data/aligned.csv. Writes data/aligned_usd.csv with columns date, xau, thb, usd.
Research only.
"""
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).parent
DATA = ROOT / "data"


def load_usd(path):
    df = pd.read_csv(path, parse_dates=["date"])
    df = df.rename(columns={"close": "usd"})
    df = df.sort_values("date").set_index("date").dropna()
    return df[~df.index.duplicated(keep="first")]["usd"]


def main():
    if not (DATA / "usd_eur.csv").exists():
        print("data/usd_eur.csv is required. Run analyze.py first.", file=__import__("sys").stderr)
        raise SystemExit(1)

    usd = load_usd(DATA / "usd_eur.csv")

    aligned = pd.read_csv(DATA / "aligned.csv", parse_dates=["date"]).sort_values("date").dropna()
    dates = aligned["date"]

    # Forward-fill to the aligned dates; backfill only if the series starts after the first date
    usd_aligned = usd.reindex(dates, method="ffill").bfill()

    out = aligned.copy()
    out["usd"] = usd_aligned.values
    out = out.dropna()
    out.to_csv(DATA / "aligned_usd.csv", index=False)
    print(f"Saved data/aligned_usd.csv: {len(out)} rows from {out['date'].min().date()} to {out['date'].max().date()}")


if __name__ == "__main__":
    main()
