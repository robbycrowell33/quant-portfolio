"""Global settings for the portfolio. Edit here, not inside model code."""

# ---- Sleeves: which models run live, and what share of account equity each gets.
# Add new models here as they come online (weights should sum to <= 1.0).
SLEEVES = {
    "tsmom": 1.0,
}
# Paper-only models are every model in MODEL_INFO with kind "signal": they run on
# their normal schedule and get tracked, but never receive capital or send orders.

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
        "version": "v1.1",
        "how_it_works": [
            "Each ETF gets a trend score: the average sign of its 3, 6 and 12 month returns, skipping the latest month.",
            "Positive score means long, negative means short. Positions are sized by inverse volatility so each asset carries similar risk.",
            "The whole book is scaled to 10% annualized volatility, capped at 40% per position and 2x gross leverage.",
            "Rebalances weekly on Friday's close. A no-trade band skips small re-sizings; only meaningful changes and direction flips trade.",
        ],
        "signals_note": "Trend score is the average of the signs: +1 = up on every lookback, -1 = down on every lookback.",
        "how_to_read": [
            "Expect it to lag in calm bull markets and to shine in long, persistent selloffs (2008, 2022).",
            "Its job in the portfolio is diversification: low correlation to stocks and 60/40.",
            "Weakness: sharp V-shaped reversals (COVID 2020) where trends flip faster than the lookbacks.",
        ],
    },
}

MODEL_INFO["xsmom"] = {
    "name": "Cross-Sectional Momentum",
    "short": "XSMOM",
    "kind": "signal",
    "status": "paper",
    "paper_reason": "Backtest Sharpe 0.08 vs T-bills (2006-2026) and it lowered the combined portfolio's Sharpe, so it gets no capital. Tracked on paper to see if it earns a spot.",
    "version": "v1",
    "started": "2026-11-27",
    "summary": "Long the 5 strongest and short the 5 weakest of 25 US sector and industry ETFs, ranked on 12-month momentum.",
    "how_it_works": [
        "Every ETF is ranked on its return over the last 12 months, skipping the most recent month.",
        "Long the top fifth, short the bottom fifth. Inside each leg, weights are inverse to volatility.",
        "The book is scaled to 10% annualized volatility, capped at 25% per position and 2x gross.",
        "Rebalances monthly on the first Friday. A no-trade band skips small re-sizings.",
    ],
    "signals_note": "Ranked on 12-month return skipping the latest month. Top 5 long, bottom 5 short, the rest flat. Signals refresh monthly.",
    "how_to_read": [
        "It bets on relative strength: winners vs losers, not the market's direction, so it's roughly market-neutral.",
        "Expect it to do well when leadership is persistent (e.g. tech or energy runs) and struggle when leadership rotates fast.",
        "Known risk: momentum crashes. When beaten-down sectors snap back hard (spring 2009), the short leg gets squeezed.",
        "Hedge test: did well in COVID 2020 (+8% while TSMOM lost 22%) but lost alongside TSMOM in 2011, 2015-16 and 2018.",
    ],
}

ASSET_CLASS = {
    "SPY": "US equity", "QQQ": "US equity", "IWM": "US equity",
    "EFA": "Intl equity", "EEM": "Intl equity",
    "TLT": "Bonds", "IEF": "Bonds",
    "GLD": "Commodities", "DBC": "Commodities",
    "VNQ": "Real estate",
    **{t: "Sectors" for t in ["XLB", "XLC", "XLE", "XLF", "XLI", "XLK", "XLP", "XLRE", "XLU", "XLV", "XLY"]},
    **{t: "Industries" for t in ["SMH", "IGV", "XBI", "IBB", "XPH", "KRE", "KIE", "XHB", "XRT",
                                 "XME", "XOP", "OIH", "ITA", "IYT"]},
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
    # v1.1 no-trade band: only trade an asset if it's off target by more than
    # max(2% of equity, 20% of its target weight). Direction flips always trade.
    "band": (0.02, 0.20),
    "rebalance": "weekly",
    "compare_v1": True,        # backtest also shows the original v1 for comparison
}

# ---- Cross-sectional momentum (sleeve #2)
XSMOM = {
    "universe": [
        # 11 sector SPDRs
        "XLB", "XLC", "XLE", "XLF", "XLI", "XLK", "XLP", "XLRE", "XLU", "XLV", "XLY",
        # industries
        "SMH", "IGV", "XBI", "IBB", "XPH", "KRE", "KIE", "XHB", "XRT",
        "XME", "XOP", "OIH", "ITA", "IYT",
    ],
    "lookback": 252,           # 12 months...
    "skip": 21,                # ...skipping the latest month (short-term reversal)
    "leg_fraction": 0.20,      # long top 20%, short bottom 20% (5 each with 25 ETFs)
    "min_per_leg": 3,
    "min_assets": 10,          # don't trade until at least 10 ETFs have full history
    "vol_window": 60,
    "cov_window": 252,
    "target_vol": 0.10,
    "max_gross": 2.0,
    "max_weight": 0.25,
    "band": (0.02, 0.20),
    "rebalance": "monthly",    # first Friday of each month
}

# ---- Backtest
BACKTEST = {
    "start": "2006-01-01",
    "rebalance": "W-FRI",      # weekly, using Friday's close
    "cost_bps": 5,             # one-way trading cost per $ traded, in basis points
    "benchmark": {"SPY": 0.6, "IEF": 0.4},
    # v1.1 financing: idle cash earns T-bills, shorts pay a borrow fee,
    # longs above 100% of equity pay T-bills + a margin spread.
    "cash_yield": True,
    "borrow_bps": 30,
    "margin_spread_bps": 100,
}

# ---- Live
LIVE = {
    "rebalance_weekday": 4,    # 0=Mon ... 4=Fri. Trades go in after Friday's close, fill Monday open.
    "min_trade_weight": 0.01,  # skip trades smaller than 1% of equity (cuts noise trades)
    "band": TSMOM["band"],     # no-trade band applied to the combined book on rebalance days
    "max_gross": 1.8,          # cap on the COMBINED book (Alpaca margin allows ~2x overnight)
}
