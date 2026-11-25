"""Sleeve #1: Time-series momentum (trend following), long/short, vol-targeted.

Every model in this repo exposes the same function:
    target_weights(prices: DataFrame, cfg: dict) -> (weights: Series, details: DataFrame)
using only data up to the last row of `prices` (no look-ahead).
"""
import numpy as np
import pandas as pd

TRADING_DAYS = 252


def signals(prices: pd.DataFrame, lookbacks, skip) -> pd.DataFrame:
    """Per-lookback signals at the last date: +1 trending up, -1 trending down.
    Return over [t-lookback, t-skip], ignoring the most recent month."""
    p_skip = prices.iloc[-1 - skip]
    out = {}
    for lb in lookbacks:
        ret = p_skip / prices.iloc[-1 - lb] - 1
        out[f"ret_{lb}d"] = ret
        out[f"sig_{lb}d"] = np.sign(ret)
    return pd.DataFrame(out)


def target_weights(prices: pd.DataFrame, cfg: dict):
    need = max(max(cfg["lookbacks"]), cfg["cov_window"]) + 1
    prices = prices.dropna(axis=1, thresh=need)          # drop assets without enough history
    if prices.shape[1] == 0 or len(prices) < need:
        return pd.Series(dtype=float), pd.DataFrame()
    prices = prices.iloc[-need:]
    rets = prices.pct_change().iloc[1:]

    # 1) Direction: average of the lookback signs, so strength is in [-1, 1]
    det = signals(prices, cfg["lookbacks"], cfg["skip"])
    strength = det[[c for c in det if c.startswith("sig_")]].mean(axis=1)

    # 2) Size: inverse volatility, so every asset carries similar risk
    vol = rets.iloc[-cfg["vol_window"]:].std() * np.sqrt(TRADING_DAYS)
    raw = strength / vol

    # 3) Scale the whole book to the portfolio vol target, using correlations
    cov = rets.iloc[-cfg["cov_window"]:].cov() * TRADING_DAYS
    port_vol = np.sqrt(raw @ cov @ raw) if raw.abs().sum() > 0 else 0.0
    w = raw * (cfg["target_vol"] / port_vol) if port_vol > 0 else raw * 0

    # 4) Risk limits
    w = w.clip(-cfg["max_weight"], cfg["max_weight"])
    gross = w.abs().sum()
    if gross > cfg["max_gross"]:
        w *= cfg["max_gross"] / gross

    det["strength"] = strength
    det["vol_ann"] = vol
    det["weight"] = w
    det["expected_port_vol"] = np.sqrt(w @ cov @ w)
    return w, det
