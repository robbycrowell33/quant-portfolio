"""Hedge test: should a candidate model get capital next to the live book?

    python tools/hedge_test.py qlv              # candidate vs TSMOM (the live book)
    python tools/hedge_test.py qlv --since 2013-07-16   # only the period a fair benchmark exists

Answers three questions from the saved backtests (run run_backtest.py first):
  1. Does adding the candidate beat simply holding T-bills with that capital?
     (blend live+candidate vs blend live+cash, same split, compared on Sharpe and drawdown)
  2. Does it pay off when the live book loses? (its returns in the live book's worst months)
  3. Is the backtest edge real? (its stats over the window where real ETF benchmarks exist,
     e.g. QUAL/USMV hedged since 2013, vs those benchmarks)
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import config  # noqa: E402
from core import data  # noqa: E402

TD = 252


def stats(r: pd.Series, rf: pd.Series) -> dict:
    r = r.dropna()
    eq = (1 + r).cumprod()
    ex = r - rf.reindex(r.index).fillna(0.0) / TD
    yrs = len(r) / TD
    return {"CAGR": eq.iloc[-1] ** (1 / yrs) - 1, "Vol": r.std() * np.sqrt(TD),
            "Sharpe": ex.mean() / r.std() * np.sqrt(TD), "Max DD": (eq / eq.cummax() - 1).min()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("candidate")
    ap.add_argument("--since", help="start date, e.g. 2013-07-16")
    ap.add_argument("--synthetic", action="store_true")
    args = ap.parse_args()
    sfx = "_synthetic" if args.synthetic else ""

    live = list(config.SLEEVES)
    eqs = {}
    for m in live + [args.candidate]:
        f = ROOT / "backtests" / f"{m}{sfx}" / "equity.csv"
        if not f.exists():
            sys.exit(f"Missing {f}. Run: python run_backtest.py {m}")
        eqs[m] = pd.read_csv(f, index_col=0, parse_dates=True)
    cand_eq = eqs[args.candidate]
    rets = pd.DataFrame({m: e[m].pct_change() for m, e in eqs.items()}).dropna()
    refs = {c: cand_eq[c].pct_change() for c in cand_eq.columns if c.endswith("_hedged")}
    if args.since:
        rets = rets.loc[args.since:]
    rf = data.synthetic_tbill(rets.index) if args.synthetic else data.get_tbill_rate(start=str(rets.index[0].date()))
    rf = rf.reindex(rets.index).ffill().fillna(0.0)

    book = sum(rets[m] * w for m, w in config.SLEEVES.items())          # today's live book
    cand = rets[args.candidate]
    cash = rf / TD
    name = config.MODEL_INFO[args.candidate]["short"]
    period = f"{rets.index[0].date()} to {rets.index[-1].date()}"
    pd.set_option("display.float_format", lambda x: f"{x:,.3f}")

    print(f"\n=== Hedge test: {name} vs live book ({', '.join(live)}), {period} ===")
    print("\n1) Blend with the candidate vs blend with T-bills (same split)")
    rows = {"Live book alone": stats(book, rf), f"{name} alone": stats(cand, rf)}
    for w in (0.2, 0.3, 0.4):
        rows[f"{1-w:.0%} book + {w:.0%} {name}"] = stats(book * (1 - w) + cand * w, rf)
        rows[f"{1-w:.0%} book + {w:.0%} cash"] = stats(book * (1 - w) + cash * w, rf)
    t1 = pd.DataFrame(rows).T
    print(t1.to_string())
    wins = [w for w in (0.2, 0.3, 0.4)
            if t1.loc[f"{1-w:.0%} book + {w:.0%} {name}", "Sharpe"] > t1.loc[f"{1-w:.0%} book + {w:.0%} cash", "Sharpe"]]
    print(f"-> Beats cash on Sharpe at {len(wins)}/3 splits." + (" PASS" if len(wins) == 3 else " FAIL" if not wins else " MIXED"))

    print("\n2) When the live book has a bad month")
    m = pd.DataFrame({"book": (1 + book).resample("ME").prod() - 1, "cand": (1 + cand).resample("ME").prod() - 1}).dropna()
    worst = m[m["book"] <= m["book"].quantile(0.10)]
    down = m[m["book"] < 0]
    print(f"   Correlation of monthly returns: {m['book'].corr(m['cand']):+.2f}")
    print(f"   Live book's worst 10% of months ({len(worst)}): book avg {worst['book'].mean():+.2%}, {name} avg {worst['cand'].mean():+.2%}")
    print(f"   In all {len(down)} down months for the book, {name} was up {(down['cand'] > 0).mean():.0%} of the time")
    cushion = worst["cand"].mean() > 0
    print("-> " + ("PASS: it tends to make money when the book is losing." if cushion else "FAIL: it doesn't cushion the book's bad months."))

    if refs:
        print("\n3) Is the edge real? Same window as the real ETF benchmarks")
        start = max(r.dropna().index[0] for r in refs.values())
        if args.since:
            start = max(start, pd.Timestamp(args.since))
        win = {name: cand.loc[start:], **{k.replace("_", " ").upper().replace(" HEDGED", " hedged"): r.loc[start:] for k, r in refs.items()}}
        before = cand.loc[:start]
        if len(before) < TD:
            print("   (less than a year of history before the benchmarks start, nothing to compare)")
            return
        win_full = {f"{name} before {start.date()}": before}
        t3 = pd.DataFrame({k: stats(v, rf) for k, v in {**win_full, **win}.items()}).T
        print(t3.to_string())
        s_after, s_before = t3.loc[name, "Sharpe"], t3.iloc[0]["Sharpe"]
        best_ref = max(t3.loc[[k for k in win if k != name], "Sharpe"])
        verdict = "holds up" if s_after >= 0.75 * s_before and s_after > best_ref else "shrinks a lot (likely hindsight bias)" if s_after < 0.5 * s_before else "partly holds"
        print(f"-> Sharpe {s_before:.2f} before vs {s_after:.2f} after {start.date()} (best real ETF: {best_ref:.2f}). Edge {verdict}.")


if __name__ == "__main__":
    main()
