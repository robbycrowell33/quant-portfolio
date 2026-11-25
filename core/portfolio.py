"""Portfolio mechanics shared by the backtest and the live runner, so both behave the same."""
import numpy as np
import pandas as pd


def apply_band(target: pd.Series, current: pd.Series, abs_band=0.02, rel_band=0.20) -> pd.Series:
    """No-trade band: keep the current weight unless the target is meaningfully different.

    An asset is traded (all the way to target) only if |target - current| exceeds
    max(abs_band, rel_band * |target|). Direction changes and full exits always trade.
    This removes the small week-to-week re-sizing that comes from noisy vol estimates.
    """
    idx = target.index.union(current.index)
    t = target.reindex(idx).fillna(0.0)
    c = current.reindex(idx).fillna(0.0)
    thresh = np.maximum(abs_band, rel_band * t.abs())
    trade = (t - c).abs() > thresh
    flip = (np.sign(t) != np.sign(c)) & (t != 0)
    exit_ = (t == 0) & (c != 0)
    return t.where(trade | flip | exit_, c)


def financing_return(w: pd.Series, rf_annual: float, borrow_bps=30, margin_spread_bps=100) -> float:
    """One day of carry on a long/short ETF book, as a fraction of equity.

    - Cash not used by longs earns the T-bill rate (short sale proceeds are NOT
      credited, which is how retail brokers work).
    - Longs beyond 100% of equity are financed at T-bills + a margin spread.
    - Shorts pay a borrow fee (cheap for liquid ETFs; ~0.3%/yr is a fair guess).
    """
    longs = float(w[w > 0].sum())
    shorts = float(-w[w < 0].sum())
    idle = 1.0 - longs
    carry = idle * rf_annual if idle >= 0 else idle * (rf_annual + margin_spread_bps / 1e4)
    carry -= shorts * borrow_bps / 1e4
    return carry / 252
