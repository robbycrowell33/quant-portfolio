"""Global settings for the portfolio. Edit here, not inside model code."""

# ---- Sleeves: which models run live, and what share of account equity each gets.
# Add new models here as they come online (weights should sum to <= 1.0).
SLEEVES = {
    "tsmom": 1.0,
}

# ---- Model registry: everything the dashboard shows about each model.
# kind:   "sleeve" = trades real (paper) capital in the Alpaca account
#         "signal" = tracked on paper only, not traded (for testing ideas live first)
# status: "live", "paper", "research", or "retired"
# Add a new model here + its code in models/ + (optionally) a backtest, and the
# dashboard picks it up automatically.
MODEL_INFO = {
    "tsmom": {
        "name": "Time-Series Momentum",
        "short": "TSMOM",
        "kind": "sleeve",
        "status": "live",
        "started": "2026-11-25",
        "summary": "Long/short trend following across 10 cross-asset ETFs, sized to 10% annualized volatility.",
        "how_it_works": [
            "Each ETF gets a trend score: the average sign of its 3, 6 and 12 month returns, skipping the latest month.",
            "Positive score means long, negative means short. Positions are sized by inverse volatility so each asset carries similar risk.",
            "The whole book is scaled to 10% annualized volatility, capped at 40% per position and 2x gross leverage.",
            "Rebalances weekly on Friday's close.",
        ],
        "how_to_read": [
            "Expect it to lag in calm bull markets and to shine in long, persistent selloffs (2008, 2022).",
            "Its job in the portfolio is diversification: low correlation to stocks and 60/40.",
            "Weakness: sharp V-shaped reversals (COVID 2020) where trends flip faster than the lookbacks.",
        ],
    },
}

ASSET_CLASS = {
    "SPY": "US equity", "QQQ": "US equity", "IWM": "US equity",
    "EFA": "Intl equity", "EEM": "Intl equity",
    "TLT": "Bonds", "IEF": "Bonds",
    "GLD": "Commodities", "DBC": "Commodities",
    "VNQ": "Real estate",
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
