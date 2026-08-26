"""Align silver (XAG/USD) with the existing XAU/THB aligned.csv date range.

If data/xag_usd.csv is missing, it is fetched from yfinance (SI=F, the
continuous COMEX silver futures front contract) and saved.  Then it is
forward-filled and aligned to data/aligned.csv.  Writes data/aligned_silver.csv
with columns date, xau, thb, xag.  Research only.
"""
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).parent
DATA = ROOT / "data"


def load_xag(path):
    df = pd.read_csv(path, parse_dates=["date"])
    df = df.rename(columns={"close": "xag"})
    df = df.sort_values("date").set_index("date").dropna()
    return df[~df.index.duplicated(keep="first")]["xag"]


def fetch_xag(start, end):
    import yfinance as yf

    print(f"Fetching SI=F from yfinance: {start} to {end}")
    d = yf.download(
        "SI=F",
        start=start,
        end=end,
        progress=False,
        multi_level_index=False,
    )
    if d.empty:
        raise RuntimeError("yfinance returned no data for SI=F")
    out = pd.DataFrame({"date": d.index.tz_localize(None).normalize(), "close": d["Close"].values})
    out = out.dropna().sort_values("date")
    out = out[~out["date"].duplicated(keep="first")]
    return out


def main():
    aligned = pd.read_csv(DATA / "aligned.csv", parse_dates=["date"]).sort_values("date").dropna()
    dates = aligned["date"]

    if not (DATA / "xag_usd.csv").exists():
        start = (dates.min() - pd.Timedelta(days=30)).strftime("%Y-%m-%d")
        end = (dates.max() + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        xag = fetch_xag(start, end)
        xag.to_csv(DATA / "xag_usd.csv", index=False)
        print(f"Saved data/xag_usd.csv: {len(xag)} rows")

    xag = load_xag(DATA / "xag_usd.csv")
    xag_aligned = xag.reindex(dates, method="ffill").bfill()

    out = aligned[["date", "xau", "thb"]].copy()
    out["xag"] = xag_aligned.values
    out = out.dropna()
    out.to_csv(DATA / "aligned_silver.csv", index=False)
    print(f"Saved data/aligned_silver.csv: {len(out)} rows from {out['date'].min().date()} to {out['date'].max().date()}")


if __name__ == "__main__":
    main()
