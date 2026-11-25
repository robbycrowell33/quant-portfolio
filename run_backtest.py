"""Backtest the TSMOM sleeve vs a 60/40 benchmark.

    python run_backtest.py              # real data (needs internet)
    python run_backtest.py --synthetic  # fake data, just to test the code
"""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

import config
from core import backtest, data, metrics
from models import tsmom

ap = argparse.ArgumentParser()
ap.add_argument("--synthetic", action="store_true")
args = ap.parse_args()

cfg, bt = config.TSMOM, config.BACKTEST
tickers = sorted(set(cfg["universe"]) | set(bt["benchmark"]))
prices = data.synthetic_prices(tickers) if args.synthetic else data.get_prices(tickers, start=bt["start"])

print(f"Data: {prices.index[0].date()} to {prices.index[-1].date()}, {len(prices.columns)} assets")
res, weights, trades = backtest.run(prices[cfg["universe"]], tsmom.target_weights, cfg,
                                    rebalance=bt["rebalance"], cost_bps=bt["cost_bps"])
bench = backtest.benchmark(prices, bt["benchmark"], res.index)
spy = prices["SPY"].reindex(res.index); spy /= spy.iloc[0]

stats = pd.DataFrame({"TSMOM": metrics.summary(res["equity"], bench),
                      "60/40": metrics.summary(bench),
                      "SPY": metrics.summary(spy)})
stats.loc["Avg gross leverage", "TSMOM"] = res["gross"].mean()
stats.loc["Avg annual turnover", "TSMOM"] = trades["turnover"].sum() / (len(res) / 252)
curves = {"TSMOM": res["equity"], "60/40": bench, "SPY": spy}
crisis = metrics.crisis_table(curves)
yearly = pd.DataFrame({k: metrics.yearly(v) for k, v in curves.items()})

out = Path("backtests/tsmom" + ("_synthetic" if args.synthetic else ""))
out.mkdir(parents=True, exist_ok=True)
pd.DataFrame({"tsmom": res["equity"], "bench_6040": bench, "spy": spy,
              "gross": res["gross"], "net": res["net"]}).to_csv(out / "equity.csv")
weights.to_csv(out / "weights.csv")
yearly.to_csv(out / "yearly.csv")
crisis.to_csv(out / "crisis.csv")
(out / "summary.json").write_text(json.dumps(
    {"synthetic": args.synthetic, "stats": stats.to_dict(), "config": cfg}, indent=2, default=float))

# chart
fig, ax = plt.subplots(3, 1, figsize=(11, 10), sharex=True,
                       gridspec_kw={"height_ratios": [3, 1.2, 1.2]})
for k, v in curves.items():
    ax[0].plot(v, label=k, lw=1.6 if k == "TSMOM" else 1)
ax[0].set_yscale("log"); ax[0].set_title("Growth of $1 (log scale)"); ax[0].legend()
for k, v in curves.items():
    ax[1].plot(metrics.drawdown(v), label=k, lw=1)
ax[1].set_title("Drawdown")
ax[2].stackplot(weights.index, weights.clip(lower=0).T.values, labels=weights.columns, step="post")
ax[2].stackplot(weights.index, weights.clip(upper=0).T.values, step="post")
ax[2].set_title("TSMOM weights (above 0 = long, below 0 = short)")
ax[2].legend(ncol=5, fontsize=7, loc="upper left")
plt.tight_layout(); plt.savefig(out / "backtest.png", dpi=130)

pd.set_option("display.float_format", lambda x: f"{x:,.3f}")
print("\n" + stats.to_string())
print("\nCrisis periods\n" + crisis.to_string())
print(f"\nSaved to {out}/")
