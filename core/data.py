"""Price data. Daily adjusted closes (dividends + splits baked in)."""
import numpy as np
import pandas as pd


def get_prices(tickers, start="2006-01-01", end=None) -> pd.DataFrame:
    import yfinance as yf

    df = yf.download(tickers, start=start, end=end, auto_adjust=True,
                     progress=False, threads=True)["Close"]
    if isinstance(df, pd.Series):
        df = df.to_frame(tickers[0])
    df = df[tickers].dropna(how="all").ffill()
    missing = [t for t in tickers if df[t].isna().all()]
    if missing:
        raise RuntimeError(f"No data for: {missing}")
    return df


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
