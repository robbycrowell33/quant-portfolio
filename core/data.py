"""Price data. Daily adjusted closes (dividends + splits baked in)."""
import numpy as np
import pandas as pd


def get_prices(tickers, start="2006-01-01", end=None, attempts=3, required=None) -> pd.DataFrame:
    """Download adjusted closes. Single-threaded with retries: yfinance's parallel
    mode can randomly fail a ticker ('database is locked' on its cache file).

    required: tickers that MUST download (default: all). Anything else that fails is
    dropped with a warning, so e.g. one bad stock in a paper model can't block live trading."""
    import tempfile
    import time
    import yfinance as yf

    try:
        yf.set_tz_cache_location(tempfile.mkdtemp())   # fresh cache, avoids lock clashes
    except Exception:
        pass
    frames, missing = {}, list(tickers)
    for attempt in range(attempts):
        if not missing:
            break
        if attempt:
            time.sleep(5 * attempt)
        df = yf.download(missing, start=start, end=end, auto_adjust=True,
                         progress=False, threads=False)["Close"]
        if isinstance(df, pd.Series):
            df = df.to_frame(missing[0])
        for t in list(missing):
            if t in df and df[t].notna().any():
                frames[t] = df[t]
                missing.remove(t)
    must = set(tickers) if required is None else set(required)
    fatal = [t for t in missing if t in must]
    if fatal:
        raise RuntimeError(f"No data for required tickers: {fatal} after {attempts} attempts")
    if missing:
        print(f"  warning: no data for {missing}, skipping them")
    have = [t for t in tickers if t in frames]
    return pd.DataFrame(frames)[have].dropna(how="all").ffill()


def synthetic_prices(tickers, start="2006-01-01", end="2026-11-20", seed=7) -> pd.DataFrame:
    """Fake prices with regime-switching trends. Only for testing the plumbing,
    the results mean nothing about real markets."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(start, end)
    n, k = len(idx), len(tickers)
    vols = rng.uniform(0.08, 0.30, k) / np.sqrt(252)
    drift = np.zeros((n, k))
    for j in range(k):
        t = 0
        while t < n:
            length = rng.integers(60, 400)
            drift[t:t + length, j] = rng.normal(0, 0.15) / 252
            t += length
    common = rng.normal(0, 0.006, (n, 1))
    rets = drift + vols * rng.standard_normal((n, k)) * 0.8 + common * rng.uniform(-0.5, 1, k)
    return pd.DataFrame(100 * np.exp(np.cumsum(rets, axis=0)), index=idx, columns=tickers)


def get_tbill_rate(start="2006-01-01", end=None) -> pd.Series:
    """3-month T-bill yield, annualized decimal (e.g. 0.045), daily. Source: Yahoo ^IRX."""
    import yfinance as yf
    for attempt in range(3):
        df = yf.download("^IRX", start=start, end=end, progress=False, threads=False, auto_adjust=False)
        if not df.empty:
            s = df["Close"]
            s = s.iloc[:, 0] if isinstance(s, pd.DataFrame) else s
            return (s / 100).rename("rf").ffill()
    raise RuntimeError("Couldn't download T-bill rates (^IRX)")


def synthetic_tbill(index) -> pd.Series:
    """Fake T-bill path for offline tests: ~0% in the 2010s, ~4-5% at the ends."""
    t = np.linspace(0, 1, len(index))
    return pd.Series(0.045 * (np.cos(t * 2 * np.pi) + 1) / 2, index=index, name="rf")
