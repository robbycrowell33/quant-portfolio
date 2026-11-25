"""Refresh the quality-stock universe from iShares QUAL's current holdings.

    python tools/refresh_quality_universe.py                 # download from iShares
    python tools/refresh_quality_universe.py --file QUAL_holdings.csv   # use a manual download

Run it about once a quarter (MSCI rebalances the index in Feb/May/Aug/Nov), then
commit data/quality_universe.csv. If the automatic download fails, download the
holdings CSV yourself from ishares.com (QUAL page > Holdings > Download) and pass --file.
"""
import argparse
import io
import sys
from datetime import date
from pathlib import Path

import pandas as pd

URL = ("https://www.ishares.com/us/products/256101/ishares-msci-usa-quality-factor-etf/"
       "1467271812596.ajax?fileType=csv&fileName=QUAL_holdings&dataType=fund")
OUT = Path(__file__).resolve().parent.parent / "data" / "quality_universe.csv"


def parse(text: str) -> pd.DataFrame:
    lines = text.splitlines()
    start = next(i for i, l in enumerate(lines) if l.startswith("Ticker,"))   # skip the fund header block
    df = pd.read_csv(io.StringIO("\n".join(lines[start:])), on_bad_lines="skip")
    df = df[df.get("Asset Class", "Equity") == "Equity"]
    df = df.dropna(subset=["Ticker"])
    df["Ticker"] = df["Ticker"].astype(str).str.strip().str.replace(r"[ .]", "-", regex=True)  # BRK B / BRK.B -> BRK-B
    df = df[df["Ticker"].str.match(r"^[A-Z][A-Z\-]*$")]
    weight = pd.to_numeric(df.get("Weight (%)"), errors="coerce")
    return pd.DataFrame({"ticker": df["Ticker"], "name": df.get("Name"), "sector": df.get("Sector"),
                         "weight_pct": weight}).drop_duplicates("ticker")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", help="path to a manually downloaded QUAL holdings CSV")
    args = ap.parse_args()
    if args.file:
        text = Path(args.file).read_text(encoding="utf-8-sig")
    else:
        import requests
        r = requests.get(URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
        r.raise_for_status()
        text = r.content.decode("utf-8-sig")
    try:
        df = parse(text)
    except StopIteration:
        sys.exit("Couldn't find the holdings table in that file. Download it manually and use --file.")
    if len(df) < 50:
        sys.exit(f"Only found {len(df)} stocks, which looks wrong. Not saving.")
    import re
    m = re.search(r'Fund Holdings as of,"([^"]+)"', text)
    df["asof"] = pd.to_datetime(m.group(1)).date().isoformat() if m else date.today().isoformat()
    OUT.parent.mkdir(exist_ok=True)
    df.sort_values("weight_pct", ascending=False).to_csv(OUT, index=False)
    print(f"Saved {len(df)} QUAL holdings to {OUT}")
    print(df.head(10).to_string(index=False))


if __name__ == "__main__":
    main()
