"""Build THB-base data for the settlement-choice experiment.

Reads data/aligned.csv (date, xau, thb) where xau is XAU/USD and thb is USD/THB.
Computes XAU/THB = XAU/USD * USD/THB and writes data/aligned_thb_base.csv with
columns date, xau_usd, usd_thb, xau_thb. Research only.
"""
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).parent
DATA = ROOT / "data"


def main():
    if not (DATA / "aligned.csv").exists():
        print("data/aligned.csv is required. Run analyze.py first.", file=__import__("sys").stderr)
        raise SystemExit(1)

    df = pd.read_csv(DATA / "aligned.csv", parse_dates=["date"]).sort_values("date").dropna()
    df["xau_usd"] = df["xau"]
    df["usd_thb"] = df["thb"]
    df["xau_thb"] = df["xau_usd"] * df["usd_thb"]

    out = df[["date", "xau_usd", "usd_thb", "xau_thb"]].copy()
    out.to_csv(DATA / "aligned_thb_base.csv", index=False)
    print(f"Saved data/aligned_thb_base.csv: {len(out)} rows from {out['date'].min().date()} to {out['date'].max().date()}")
    print(f"  XAU/USD: {out['xau_usd'].iloc[0]:.4f} ... {out['xau_usd'].iloc[-1]:.4f}")
    print(f"  USD/THB: {out['usd_thb'].iloc[0]:.4f} ... {out['usd_thb'].iloc[-1]:.4f}")
    print(f"  XAU/THB: {out['xau_thb'].iloc[0]:.4f} ... {out['xau_thb'].iloc[-1]:.4f}")


if __name__ == "__main__":
    main()
