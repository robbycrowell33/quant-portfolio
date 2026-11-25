# Quant Portfolio (paper trading)

A multi-model systematic portfolio, run on live market data and paper traded on Alpaca.
Each model is a **sleeve** with its own capital share (`config.SLEEVES`). The live job
combines sleeve targets into one book.

| Sleeve | Model | Status |
|---|---|---|
| `tsmom` | Time-series momentum, long/short, 10 cross-asset ETFs, 10% vol target | live |

## TSMOM in one paragraph
Each Friday, every ETF gets a trend score: the average sign of its 3, 6 and 12 month
returns (skipping the latest month). Positions are sized by inverse volatility so
each asset carries similar risk. The whole book is then scaled to 10% annualized
volatility using the covariance matrix, with caps of 40% per position and 2x gross.

## Setup
```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python run_backtest.py            # real backtest, outputs in backtests/tsmom/
python run_live.py --test         # offline smoke test (fake data + fake broker)

export ALPACA_API_KEY=...         # PAPER keys from alpaca.markets
export ALPACA_SECRET_KEY=...
python run_live.py --dry-run      # see what it would trade, sends nothing
python run_live.py --force        # first real paper rebalance
```

## Automation
`.github/workflows/daily.yml` runs `run_live.py` every weekday after the close and
commits snapshots to `live/`. Add `ALPACA_API_KEY` and `ALPACA_SECRET_KEY` under
repo Settings → Secrets and variables → Actions.

## Layout
```
config.py            all settings
models/tsmom.py      sleeve #1 (every model exposes target_weights(prices, cfg))
core/                data, backtest engine, metrics, broker
run_backtest.py      historical test vs 60/40
run_live.py          daily live job
live/                equity.csv, positions, signals, trades (written by the job)
```

## Known simplifications
- Cash earns 0% and short borrow costs are ignored in the backtest.
- Trading cost is a flat 5 bps per side.
- Backtest fills at the close; live orders fill at the next open.

## Dashboard
`dashboard/build.py` turns `live/` and `backtests/` into a one-page site (`site/index.html`).
`.github/workflows/dashboard.yml` rebuilds and publishes it to GitHub Pages after every
daily run and on every push. Preview locally with `python dashboard/build.py && open site/index.html`.

To add a model: put its code in `models/`, add an entry to `config.MODEL_INFO`
(and `config.SLEEVES` if it trades), run its backtest into `backtests/<id>/`, and push.
It shows up as its own tab automatically.
