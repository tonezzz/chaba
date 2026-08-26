"""Align USD/EUR close prices with the existing aligned.csv date range.

Reads data/usd_eur.csv, forward-fills missing days and aligns to data/aligned.csv.
Writes data/aligned_usd.csv with columns date, xau, thb, usd.
"""
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).parent
DATA = ROOT / "data"


def main():
    if not (DATA / "usd_eur.csv").exists():
        print("data/usd_eur.csv not found.", file=__import__("sys").stderr)
        raise SystemExit(1)

    usd = pd.read_csv(DATA / "usd_eur.csv")
    usd["value"] = pd.to_numeric(usd["close"], errors="coerce")
    usd["timestamp"] = pd.to_datetime(usd["date"])
    usd = usd.sort_values("timestamp").set_index("timestamp").dropna()
    usd = usd[~usd.index.duplicated(keep="first")]["value"]

    aligned = pd.read_csv(DATA / "aligned.csv", parse_dates=["date"]).sort_values("date").dropna()
    dates = aligned["date"]

    usd_aligned = usd.reindex(dates, method="ffill").bfill()

    out = aligned.copy()
    out["usd"] = usd_aligned.values
    out = out.dropna()
    out.to_csv(DATA / "aligned_usd.csv", index=False)
    print(f"Saved data/aligned_usd.csv: {len(out)} rows from {out['date'].min().date()} to {out['date'].max().date()}")


if __name__ == "__main__":
    main()
