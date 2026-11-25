"""Sleeve #2: Cross-sectional momentum on US sector & industry ETFs, long/short.

Rank every ETF by its 12-month return skipping the latest month (the classic
"12-1" momentum of Jegadeesh & Titman). Long the top fifth, short the bottom fifth,
inverse-volatility weights inside each leg, then scale the book to the vol target.

Same interface as every model: target_weights(prices, cfg) -> (weights, details).
"""
import numpy as np
import pandas as pd

TRADING_DAYS = 252


def target_weights(prices: pd.DataFrame, cfg: dict):
    need = max(cfg["lookback"], cfg["cov_window"]) + 1
    window = prices.iloc[-need:]
    window = window.loc[:, window.notna().all()]           # only ETFs with full history in the window
    n = window.shape[1]
    if len(prices) < need or n < cfg["min_assets"]:
        return pd.Series(dtype=float), pd.DataFrame()

    rets = window.pct_change().iloc[1:]
    mom = window.iloc[-1 - cfg["skip"]] / window.iloc[-1 - cfg["lookback"]] - 1   # 12-1 return
    rank = mom.rank(ascending=False, method="first")
    k = max(cfg["min_per_leg"], int(round(n * cfg["leg_fraction"])))
    longs, shorts = rank.index[rank <= k], rank.index[rank > n - k]

    vol = rets.iloc[-cfg["vol_window"]:].std() * np.sqrt(TRADING_DAYS)
    raw = pd.Series(0.0, index=window.columns)
    inv = 1 / vol
    raw[longs] = inv[longs] / inv[longs].sum()             # each leg sums to 1 (gross 2 before scaling)
    raw[shorts] = -inv[shorts] / inv[shorts].sum()

    cov = rets.iloc[-cfg["cov_window"]:].cov() * TRADING_DAYS
    port_vol = float(np.sqrt(raw @ cov @ raw))
    w = raw * (cfg["target_vol"] / port_vol) if port_vol > 0 else raw * 0

    w = w.clip(-cfg["max_weight"], cfg["max_weight"])
    gross = w.abs().sum()
    if gross > cfg["max_gross"]:
        w *= cfg["max_gross"] / gross

    det = pd.DataFrame({
        "ret_12_1": mom,
        "rank": rank.astype(int),
        "vol_ann": vol,
        "weight": w,
    })
    det["leg"] = np.where(det.index.isin(longs), "long", np.where(det.index.isin(shorts), "short", "-"))
    det["expected_port_vol"] = float(np.sqrt(w @ cov @ w))
    return w.reindex(prices.columns).fillna(0.0), det.sort_values("rank")
