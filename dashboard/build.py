"""Build the dashboard: reads live/ and backtests/, writes site/index.html.

    python dashboard/build.py          # real data (needs internet for benchmark prices)
    python dashboard/build.py --test   # synthetic data, for checking the page offline

Everything the page shows is embedded as JSON, so the site is a single static file.
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import config  # noqa: E402
from core import data, metrics  # noqa: E402
from models import REGISTRY, required_tickers  # noqa: E402


def series(s: pd.Series, digits=5):
    s = s.dropna()
    return [[d.strftime("%Y-%m-%d"), round(float(v), digits)] for d, v in s.items()]


def clean(obj):
    """Make stats JSON-safe (NaN -> None)."""
    if isinstance(obj, dict):
        return {k: clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean(v) for v in obj]
    if isinstance(obj, (float, np.floating)):
        return None if not np.isfinite(obj) else round(float(obj), 6)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    return obj


def read_csv(path, **kw):
    return pd.read_csv(path, **kw) if path.exists() else None


def live_stats(eq: pd.Series, bench: pd.Series = None):
    if eq is None or len(eq) < 2:
        return None
    out = {"Total return": eq.iloc[-1] / eq.iloc[0] - 1,
           "Max drawdown": metrics.drawdown(eq).min(),
           "Days live": len(eq)}
    r = eq.pct_change().dropna()
    if len(r) >= 20:   # annualized stats are meaningless on a handful of days
        out["Volatility"] = r.std() * np.sqrt(252)
        out["Sharpe"] = r.mean() / r.std() * np.sqrt(252) if r.std() > 0 else None
    if bench is not None and len(bench.dropna()) >= 2:
        b = bench.reindex(eq.index).ffill()
        out["60/40 return"] = b.iloc[-1] / b.iloc[0] - 1
        if len(r) >= 20:
            out["Correlation to 60/40"] = r.corr(b.pct_change().dropna())
    return out


def sleeve_shadow(weights_csv: Path, prices: pd.DataFrame):
    """Rebuild a sleeve's own P&L from its logged weights (standalone scale) and daily
    prices. Weights are held from each rebalance until the next (drift ignored)."""
    w = read_csv(weights_csv, parse_dates=["date"])
    if w is None or w.empty:
        return None
    w = w.drop_duplicates("date", keep="last").set_index("date").sort_index().fillna(0.0)
    cols = [c for c in w.columns if c in prices.columns and c != "date"]
    rets = prices[cols].pct_change()
    held = w[cols].reindex(rets.index).ffill().shift(1)       # earn the day after deciding
    daily = (held * rets).sum(axis=1).loc[w.index[0]:]
    if len(daily) < 2:
        return None
    return (1 + daily.iloc[1:]).cumprod().reindex(daily.index).fillna(1.0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true")
    args = ap.parse_args()

    live_dir = ROOT / ("live_test" if args.test else "live")
    bt_suffix = "_synthetic" if args.test else ""
    bench_mix = config.BACKTEST["benchmark"]

    # ---------- account level ----------
    eq_df = read_csv(live_dir / "equity.csv", parse_dates=["date"])
    account = None
    prices = None
    if eq_df is not None and not eq_df.empty:
        eq_df = eq_df.drop_duplicates("date", keep="last").set_index("date").sort_index()
        start = eq_df.index[0]
        tracked = [m for m in config.MODEL_INFO if m in REGISTRY and (m in config.SLEEVES or config.MODEL_INFO[m].get("kind") == "signal")]
        tickers = sorted(set(bench_mix) | {t for m in tracked for t in REGISTRY[m][1]["universe"]})
        if args.test:
            prices = data.synthetic_prices(tickers).loc[start - pd.Timedelta(days=10):eq_df.index[-1]]
        else:
            prices = data.get_prices(tickers, start=(start - pd.Timedelta(days=10)).strftime("%Y-%m-%d"),
                                     required=set(bench_mix) | required_tickers(config.SLEEVES))
        b_rets = sum(prices[t].pct_change() * w for t, w in bench_mix.items()).loc[start:]
        bench = (1 + b_rets.iloc[1:]).cumprod().reindex(b_rets.index).fillna(1.0)
        bench = bench.reindex(eq_df.index).ffill() * eq_df["equity"].iloc[0]
        last = eq_df.iloc[-1]
        prev = eq_df.iloc[-2] if len(eq_df) > 1 else last
        account = {
            "start_equity": float(eq_df["equity"].iloc[0]),
            "equity": float(last["equity"]),
            "cash": float(last["cash"]),
            "long_mv": float(last["long_mv"]),
            "short_mv": float(last["short_mv"]),
            "day_change": float(last["equity"] - prev["equity"]),
            "curve": series(eq_df["equity"], 2),
            "bench": series(bench, 2),
            "stats": live_stats(eq_df["equity"], bench),
        }

    pos = json.loads((live_dir / "positions_latest.json").read_text()) if (live_dir / "positions_latest.json").exists() else {"positions": []}
    owner = {t: config.MODEL_INFO[m]["short"] for m in config.SLEEVES for t in REGISTRY[m][1]["universe"]}
    for p in pos["positions"]:
        p["asset_class"] = config.ASSET_CLASS.get(p["ticker"], "Other")
        p["sleeve"] = owner.get(p["ticker"], "–")
    sig = json.loads((live_dir / "signals_latest.json").read_text()) if (live_dir / "signals_latest.json").exists() else {"sleeves": {}}
    trades = read_csv(live_dir / "trades.csv")
    trades = [] if trades is None else trades.tail(200).iloc[::-1].drop(columns=["order_id"], errors="ignore").to_dict(orient="records")

    # ---------- per model ----------
    models = []
    for mid, info in config.MODEL_INFO.items():
        m = {"id": mid, **info, "allocation": config.SLEEVES.get(mid, 0.0)}
        paper = info.get("kind") == "signal"
        m["paper"] = paper
        wfile = live_dir / "paper" / f"{mid}_weights.csv" if paper else live_dir / f"sleeve_weights_{mid}.csv"
        if prices is not None and (paper or m["allocation"] > 0):
            shadow = sleeve_shadow(wfile, prices)
            if shadow is not None:
                bench_m = (prices[list(bench_mix)].pct_change().mul(pd.Series(bench_mix)).sum(axis=1)
                           .loc[shadow.index[0]:])
                bench_m = (1 + bench_m.iloc[1:]).cumprod().reindex(bench_m.index).fillna(1.0)
                m["live"] = {"curve": series(shadow), "bench": series(bench_m),
                             "stats": live_stats(shadow, bench_m)}
        src, asof_key = ("paper", "paper_asof") if paper else ("sleeves", "sleeve_asof")
        m["signals"] = sig.get(src, {}).get(mid, [])
        m["signals_asof"] = sig.get(asof_key, {}).get(mid, sig.get("asof") if not paper else None)
        m["rebalance"] = REGISTRY[mid][1].get("rebalance", "weekly")

        bt_dir = ROOT / "backtests" / f"{mid}{bt_suffix}"
        if (bt_dir / "equity.csv").exists():
            eq = pd.read_csv(bt_dir / "equity.csv", index_col=0, parse_dates=True)
            wk = eq.resample("W-FRI").last()
            summ = json.loads((bt_dir / "summary.json").read_text())
            crisis = pd.read_csv(bt_dir / "crisis.csv", index_col=0)
            yearly = pd.read_csv(bt_dir / "yearly.csv", index_col=0)
            m["backtest"] = {
                "synthetic": summ.get("synthetic", False),
                "curves": {"model": series(wk[mid] if mid in wk else wk.iloc[:, 0], 4),
                           "bench": series(wk["bench_6040"], 4), "spy": series(wk["spy"], 4)},
                "drawdown": {"model": series(metrics.drawdown(wk.iloc[:, 0]), 4),
                             "bench": series(metrics.drawdown(wk["bench_6040"]), 4),
                             "spy": series(metrics.drawdown(wk["spy"]), 4)},
                "stats": summ["stats"],
                "crisis": crisis.reset_index(names="period").to_dict(orient="records"),
                "yearly": yearly.reset_index(names="year").to_dict(orient="records"),
            }
        models.append(m)

    # ---------- combined portfolio backtest ----------
    portfolio_bt = None
    pdir = ROOT / "backtests" / f"portfolio{bt_suffix}"
    if len(config.SLEEVES) > 1 and (pdir / "equity.csv").exists():
        pe = pd.read_csv(pdir / "equity.csv", index_col=0, parse_dates=True).resample("W-FRI").last()
        ps = json.loads((pdir / "summary.json").read_text())
        names = {m: config.MODEL_INFO[m]["short"] for m in ps["allocation"]}
        portfolio_bt = {
            "allocation": {names[m]: w for m, w in ps["allocation"].items()},
            "curves": {"Portfolio": series(pe["portfolio"], 4), "60/40": series(pe["bench_6040"], 4),
                       **{names[m]: series(pe[m], 4) for m in ps["allocation"]}},
            "stats": ps["stats"],
            "correlation": {names[a]: {names[b]: v for b, v in row.items()} for a, row in ps["correlation"].items()},
            "crisis": ps["crisis"],
            "synthetic": ps.get("synthetic", False),
        }

    payload = clean({
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="minutes"),
        "asof": pos.get("asof") or (account["curve"][-1][0] if account else None),
        "test_data": args.test,
        "account": account,
        "positions": pos["positions"],
        "trades": trades,
        "models": models,
        "portfolio_bt": portfolio_bt,
    })
    template = (ROOT / "dashboard" / "template.html").read_text()
    html = template.replace("/*__DATA__*/null", json.dumps(payload, default=str))
    out = ROOT / "site"
    out.mkdir(exist_ok=True)
    (out / "index.html").write_text(html)
    print(f"Wrote {out / 'index.html'} ({len(html) / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
