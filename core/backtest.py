"""Generic backtester. Works for any model that follows the target_weights() interface.

Timing: weights are decided with data through the rebalance-day close and earn
returns starting the NEXT day, so there's no look-ahead. Between rebalances the
weights drift with prices, like a real portfolio.
"""
import pandas as pd


def run(prices: pd.DataFrame, model_fn, cfg: dict, rebalance="W-FRI", cost_bps=5, start=None):
    rets = prices.pct_change().fillna(0.0)
    dates = prices.index
    reb_dates = set(prices.resample(rebalance).last().index)
    # map calendar rebalance labels to the last actual trading day on/before them
    reb_days = set(dates[dates.searchsorted(list(reb_dates), side="right") - 1])

    w = pd.Series(0.0, index=prices.columns)
    equity, rows, weights_log, trades_log = 1.0, [], {}, []
    for i in range(1, len(dates)):
        d, prev = dates[i], dates[i - 1]
        # earn today's return on yesterday's holdings
        r = rets.loc[d]
        day_ret = float((w * r).sum())
        cash = 1 - w.sum()                     # longs use cash, shorts add cash; cash earns 0 here
        equity *= 1 + day_ret
        # drift weights with prices
        grown = w * (1 + r)
        denom = grown.sum() + cash
        w = grown / denom if denom != 0 else grown
        cost = 0.0
        if d in reb_days and (start is None or d >= pd.Timestamp(start)):
            target, _ = model_fn(prices.loc[:d], cfg)
            target = target.reindex(prices.columns).fillna(0.0)
            turnover = float((target - w).abs().sum())
            cost = turnover * cost_bps / 1e4
            equity *= 1 - cost
            trades_log.append({"date": d, "turnover": turnover})
            w = target
            weights_log[d] = target
        rows.append({"date": d, "ret": day_ret - cost, "equity": equity,
                     "gross": float(w.abs().sum()), "net": float(w.sum())})

    res = pd.DataFrame(rows).set_index("date")
    first = min(weights_log) if weights_log else res.index[0]
    res = res.loc[first:]
    res["equity"] /= res["equity"].iloc[0]
    return res, pd.DataFrame(weights_log).T, pd.DataFrame(trades_log).set_index("date")


def benchmark(prices: pd.DataFrame, mix: dict, index) -> pd.Series:
    """Fixed-mix benchmark (e.g. 60/40), rebalanced monthly."""
    def mix_fn(p, cfg):
        return pd.Series(mix), None
    res, _, _ = run(prices[list(mix)], mix_fn, {}, rebalance="ME", cost_bps=0)
    eq = res["equity"].reindex(index).ffill()
    return eq / eq.dropna().iloc[0]
