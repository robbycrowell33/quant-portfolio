"""Quality low-vol, market-hedged.

Universe: QUAL's current holdings (data/quality_universe.csv), so the quality screen
is done by MSCI. Within that list: go long the N least volatile stocks (1-year daily
vol), weighted inverse to vol, and short an S&P 500 ETF sized to the longs' beta so
the sleeve has roughly zero market exposure. What's left is a bet that calm,
high-quality companies beat the market on a risk-adjusted basis (the "low-risk anomaly").

Same interface as every model: target_weights(prices, cfg) -> (weights, details).
"""
import numpy as np
import pandas as pd

TRADING_DAYS = 252


def target_weights(prices: pd.DataFrame, cfg: dict):
    hedge = cfg["hedge"]
    need = max(cfg["vol_window"], cfg["beta_window"]) + 1
    if hedge not in prices or len(prices) < need:
        return pd.Series(dtype=float), pd.DataFrame()
    window = prices.iloc[-need:]
    stocks = [c for c in window.columns if c != hedge and window[c].notna().all()]
    if len(stocks) < cfg["min_assets"] or window[hedge].isna().any():
        return pd.Series(dtype=float), pd.DataFrame()

    rets = window[stocks + [hedge]].pct_change().iloc[1:]
    vol = rets[stocks].iloc[-cfg["vol_window"]:].std() * np.sqrt(TRADING_DAYS)
    mkt = rets[hedge].iloc[-cfg["beta_window"]:]
    beta = rets[stocks].iloc[-cfg["beta_window"]:].apply(lambda s: s.cov(mkt)) / mkt.var()

    picks = vol.nsmallest(cfg["n_long"]).index
    inv = 1 / vol[picks]
    longs = inv / inv.sum()                                    # sums to 1

    def book(lw):
        w = lw.copy()
        w[hedge] = -max(0.0, float((lw * beta[lw.index]).sum()))   # short the index to cancel the longs' beta (never long)
        return w

    raw = book(longs)
    cov = rets[raw.index].cov() * TRADING_DAYS
    port_vol = float(np.sqrt(raw @ cov @ raw))
    k = cfg["target_vol"] / port_vol if port_vol > 0 else 0.0
    w = book((longs * k).clip(upper=cfg["max_weight"]))       # cap single stocks, then re-hedge
    gross = w.abs().sum()
    if gross > cfg["max_gross"]:
        w *= cfg["max_gross"] / gross

    det = pd.DataFrame({"vol_ann": vol, "beta": beta, "weight": w.reindex(vol.index).fillna(0.0)})
    det["rank"] = det["vol_ann"].rank(method="first").astype(int)
    det["leg"] = np.where(det["weight"] > 0, "long", "-")
    det = det.sort_values("rank")
    hedge_row = pd.DataFrame({"vol_ann": [float(rets[hedge].std() * np.sqrt(TRADING_DAYS))], "beta": [1.0],
                              "weight": [w[hedge]], "rank": [0], "leg": ["hedge"]}, index=[hedge])
    det = pd.concat([hedge_row, det])
    det["long_beta"] = float((w.drop(hedge) * beta[w.drop(hedge).index]).sum())
    det["net_beta"] = det["long_beta"] + w[hedge]
    det["expected_port_vol"] = float(np.sqrt(w @ (rets[w.index].cov() * TRADING_DAYS) @ w))
    return w.reindex(prices.columns).fillna(0.0), det
