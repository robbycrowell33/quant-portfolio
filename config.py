"""Global settings for the portfolio. Edit here, not inside model code."""

# ---- Sleeves: which models run live, and what share of account equity each gets.
# Add new models here as they come online (weights should sum to <= 1.0).
SLEEVES = {
    "tsmom": 1.0,
}

# ---- Time-series momentum (sleeve #1)
TSMOM = {
    "universe": ["SPY", "QQQ", "IWM", "EFA", "EEM",   # equities
                 "TLT", "IEF",                         # bonds
                 "GLD", "DBC",                         # commodities
                 "VNQ"],                               # real estate
    # Lookbacks in trading days. Each signal skips the most recent month (21d).
    "lookbacks": [63, 126, 252],
    "skip": 21,
    "vol_window": 60,          # days of returns used for each asset's volatility
    "cov_window": 252,         # days used for the portfolio-level covariance
    "target_vol": 0.10,        # annualized portfolio volatility target
    "max_gross": 2.0,          # cap on sum(|weights|), i.e. max 2x leverage
    "max_weight": 0.40,        # cap on any single position (long or short)
}

# ---- Backtest
BACKTEST = {
    "start": "2006-01-01",
    "rebalance": "W-FRI",      # weekly, using Friday's close
    "cost_bps": 5,             # one-way trading cost per $ traded, in basis points
    "benchmark": {"SPY": 0.6, "IEF": 0.4},
}

# ---- Live
LIVE = {
    "rebalance_weekday": 4,    # 0=Mon ... 4=Fri. Trades go in after Friday's close, fill Monday open.
    "min_trade_weight": 0.01,  # skip trades smaller than 1% of equity (cuts noise trades)
}
