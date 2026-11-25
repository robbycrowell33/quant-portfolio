"""Backtest one model, or all live sleeves plus the combined portfolio.

    python run_backtest.py tsmom          # one model
    python run_backtest.py xsmom
    python run_backtest.py all            # every model in the registry + combined portfolio
    add --synthetic to test offline with fake data

Outputs go to backtests/<model>/ (and backtests/portfolio/ for the combination);
the dashboard reads them from there.
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
from models import REGISTRY

bt = config.BACKTEST


def load_inputs(tickers, synthetic):
    prices = data.synthetic_prices(tickers) if synthetic else data.get_prices(tickers, start=bt["start"])
    rf = None
    if bt.get("cash_yield"):
        rf = data.synthetic_tbill(prices.index) if synthetic else data.get_tbill_rate(start=bt["start"])
    return prices, rf


def run_model(mid, prices, rf, synthetic):
    fn, cfg = REGISTRY[mid]
    short = config.MODEL_INFO[mid]["short"]
    kw = dict(rebalance=bt["rebalance"], cost_bps=bt["cost_bps"], monthly=cfg.get("rebalance") == "monthly")
    fin = dict(rf=rf, borrow_bps=bt["borrow_bps"], margin_spread_bps=bt["margin_spread_bps"])
    res, weights, trades = backtest.run(prices[cfg["universe"]], fn, cfg, band=cfg.get("band"), **fin, **kw)
    curves = {short: res["equity"]}
    runs = {short: (res, trades)}
    if cfg.get("compare_v1"):     # original version: no band, cash earns 0
        res1, _, trades1 = backtest.run(prices[cfg["universe"]], fn, cfg, **kw)
        res1 = res1.reindex(res.index).ffill()
        curves[short + " v1"] = res1["equity"]
        runs[short + " v1"] = (res1, trades1)

    bench = backtest.benchmark(prices, bt["benchmark"], res.index)
    spy = prices["SPY"].reindex(res.index); spy /= spy.iloc[0]
    stats = {k: metrics.summary(v, bench, rf) for k, v in curves.items()}
    stats["60/40"] = metrics.summary(bench, rf=rf)
    stats["SPY"] = metrics.summary(spy, rf=rf)
    stats = pd.DataFrame(stats)
    yrs = len(res) / 252
    for k, (r_, t_) in runs.items():
        stats.loc["Avg gross leverage", k] = r_["gross"].mean()
        stats.loc["Avg annual turnover", k] = t_["turnover"].sum() / yrs
        stats.loc["Trading cost / yr", k] = t_["turnover"].sum() / yrs * bt["cost_bps"] / 1e4

    # correlation to the other sleeves' backtests (if they've been run)
    suffix = "_synthetic" if synthetic else ""
    for other in REGISTRY:
        f = Path(f"backtests/{other}{suffix}/equity.csv")
        if other != mid and f.exists():
            o = pd.read_csv(f, index_col=0, parse_dates=True)[other]
            stats.loc[f"Correlation to {config.MODEL_INFO[other]['short']}", short] = \
                res["equity"].pct_change().corr(o.pct_change().reindex(res.index))

    curves.update({"60/40": bench, "SPY": spy})
    crisis = metrics.crisis_table(curves)
    yearly = pd.DataFrame({k: metrics.yearly(v) for k, v in curves.items()})

    out = Path(f"backtests/{mid}{suffix}")
    out.mkdir(parents=True, exist_ok=True)
    eq = {mid: res["equity"]}
    if cfg.get("compare_v1"):
        eq[f"{mid}_v1"] = curves[short + " v1"]
    pd.DataFrame({**eq, "bench_6040": bench, "spy": spy, "gross": res["gross"], "net": res["net"]}).to_csv(out / "equity.csv")
    weights.to_csv(out / "weights.csv")
    yearly.to_csv(out / "yearly.csv")
    crisis.to_csv(out / "crisis.csv")
    (out / "summary.json").write_text(json.dumps(
        {"synthetic": synthetic, "version": config.MODEL_INFO[mid].get("version"), "stats": stats.to_dict(),
         "config": cfg, "notes": "Sharpe/Sortino are in excess of 3-month T-bills. Includes trading costs, "
                                 "cash yield on idle cash, short borrow fees and margin cost."},
        indent=2, default=float))

    fig, ax = plt.subplots(3, 1, figsize=(11, 10), sharex=True, gridspec_kw={"height_ratios": [3, 1.2, 1.2]})
    for k, v in curves.items():
        ax[0].plot(v, label=k, lw=1.6 if k == short else 1, ls=":" if k.endswith(" v1") else "-")
    ax[0].set_yscale("log"); ax[0].set_title("Growth of $1 (log scale)"); ax[0].legend()
    for k, v in curves.items():
        ax[1].plot(metrics.drawdown(v), label=k, lw=1)
    ax[1].set_title("Drawdown")
    ax[2].stackplot(weights.index, weights.clip(lower=0).T.values, labels=weights.columns, step="post")
    ax[2].stackplot(weights.index, weights.clip(upper=0).T.values, step="post")
    ax[2].set_title(f"{short} weights (above 0 = long, below 0 = short)")
    ax[2].legend(ncol=8, fontsize=6, loc="upper left")
    plt.tight_layout(); plt.savefig(out / "backtest.png", dpi=130); plt.close(fig)

    print(f"\n===== {config.MODEL_INFO[mid]['name']} =====")
    print(stats.to_string())
    print("\nCrisis periods\n" + crisis.to_string())
    print(f"Saved to {out}/")
    return res


def run_portfolio(results, prices, rf, synthetic):
    """Combine the sleeves' backtests with today's capital split (rebalanced daily)."""
    rets = pd.DataFrame({m: r["equity"].pct_change() for m, r in results.items()}).dropna()
    alloc = pd.Series(config.SLEEVES)
    port = (1 + (rets[alloc.index] * alloc).sum(axis=1)).cumprod()
    port /= port.iloc[0]
    bench = backtest.benchmark(prices, bt["benchmark"], port.index)
    sleeves = {config.MODEL_INFO[m]["short"]: (1 + rets[m]).cumprod() for m in alloc.index}
    curves = {"Portfolio": port, **sleeves, "60/40": bench}
    stats = pd.DataFrame({k: metrics.summary(v, bench, rf) for k, v in curves.items()})
    corr = rets.corr()
    out = Path("backtests/portfolio" + ("_synthetic" if synthetic else ""))
    out.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"portfolio": port, **{m: (1 + rets[m]).cumprod() for m in alloc.index},
                  "bench_6040": bench}).to_csv(out / "equity.csv")
    (out / "summary.json").write_text(json.dumps(
        {"synthetic": synthetic, "allocation": config.SLEEVES, "stats": stats.to_dict(),
         "correlation": corr.round(3).to_dict(),
         "crisis": metrics.crisis_table(curves).reset_index(names="period").to_dict(orient="records")},
        indent=2, default=float))
    print("\n===== Combined portfolio " + " / ".join(f"{m} {w:.0%}" for m, w in config.SLEEVES.items()) + " =====")
    print(stats.to_string())
    print("\nSleeve correlation (daily returns)\n" + corr.round(2).to_string())
    print(f"Saved to {out}/")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("model", nargs="?", default="all", choices=["all", *REGISTRY])
    ap.add_argument("--synthetic", action="store_true")
    args = ap.parse_args()
    pd.set_option("display.float_format", lambda x: f"{x:,.3f}")

    ids = list(REGISTRY) if args.model == "all" else [args.model]
    tickers = sorted({t for m in ids for t in REGISTRY[m][1]["universe"]} | set(bt["benchmark"]))
    prices, rf = load_inputs(tickers, args.synthetic)
    print(f"Data: {prices.index[0].date()} to {prices.index[-1].date()}, {len(prices.columns)} assets")
    results = {m: run_model(m, prices, rf, args.synthetic) for m in ids}
    if args.model == "all" and all(m in results for m in config.SLEEVES):
        # rerun correlations now that every sleeve's file exists is unnecessary: portfolio covers it
        run_portfolio({m: results[m] for m in config.SLEEVES}, prices, rf, args.synthetic)
