"""Daily live job (paper trading). Run after the market close.

    python run_live.py               # normal run: logs every day, rebalances on Fridays
    python run_live.py --force       # rebalance today regardless of weekday
    python run_live.py --dry-run     # compute everything, send no orders
    python run_live.py --test        # offline: synthetic prices + fake broker

What it does:
  1. Pull recent prices.
  2. On rebalance day: each sleeve computes target weights, they're combined by
     the capital split in config.SLEEVES, and converted to share targets.
  3. Every day: trade any position that differs from the saved share targets.
     (A long -> short flip has to happen in two steps on Alpaca: close today,
     open the short on the next run. Daily reconciling handles that.)
  4. Write snapshots to live/ for the dashboard.
"""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

import config
from core import broker as brokers, data
from models import tsmom

MODELS = {"tsmom": (tsmom.target_weights, config.TSMOM)}
LIVE_DIR = Path("live")


def combined_targets(prices):
    total, per_sleeve, details = pd.Series(dtype=float), {}, {}
    for name, alloc in config.SLEEVES.items():
        fn, cfg = MODELS[name]
        w, det = fn(prices[cfg["universe"]], cfg)
        per_sleeve[name] = (w * alloc).to_dict()
        details[name] = det.reset_index(names="ticker").to_dict(orient="records")
        total = total.add(w * alloc, fill_value=0.0)
    return total, per_sleeve, details


def to_shares(weights, equity, last_px):
    # round toward zero so we never exceed the intended exposure
    return {t: int(w * equity / last_px[t]) for t, w in weights.items() if int(w * equity / last_px[t]) != 0}


def plan_orders(target, current, last_px, equity, min_w):
    orders = []
    for t in sorted(set(target) | set(current)):
        tgt, cur = target.get(t, 0), current.get(t, 0)
        diff = tgt - cur
        if diff == 0:
            continue
        if abs(diff * last_px[t]) < min_w * equity and tgt != 0:
            continue                         # too small to bother (unless we're exiting fully)
        if cur != 0 and tgt != 0 and (cur > 0) != (tgt > 0):
            orders.append((t, -cur, "close (flip; reopen next run)"))
        else:
            orders.append((t, diff, "rebalance"))
    # reduce exposure first so buying power is free for the rest
    return sorted(orders, key=lambda o: abs(current.get(o[0], 0) + o[1]) > abs(current.get(o[0], 0)))


def append_csv(path, row: dict):
    df = pd.DataFrame([row])
    df.to_csv(path, mode="a", header=not path.exists(), index=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--asof", help="(test mode) pretend today is this date")
    args = ap.parse_args()

    universe = sorted({t for n in config.SLEEVES for t in MODELS[n][1]["universe"]})
    if args.test:
        prices = data.synthetic_prices(universe)
        if args.asof:
            prices = prices.loc[:args.asof]
        brk = TEST_BROKER
        brk.px = prices.iloc[-1].to_dict()
        live_dir = Path("live_test")
    else:
        start = (pd.Timestamp.today() - pd.DateOffset(days=600)).strftime("%Y-%m-%d")
        prices = data.get_prices(universe, start=start)
        brk = brokers.AlpacaBroker()
        live_dir = LIVE_DIR
    live_dir.mkdir(exist_ok=True)
    state_path = live_dir / "targets.json"

    asof = prices.index[-1]
    last_px = prices.iloc[-1]
    # Re-running on the same date (holiday, manual rerun) is safe: no new targets
    # unless it's rebalance day, orders only fill gaps vs the saved targets, and the
    # snapshot for that date gets replaced rather than duplicated.
    acct = brk.account()
    current = brk.positions()
    is_reb_day = args.force or asof.weekday() == config.LIVE["rebalance_weekday"] or not state_path.exists()

    if is_reb_day:
        weights, per_sleeve, details = combined_targets(prices)
        target_shares = to_shares(weights, acct["equity"], last_px)
        state = {"asof": str(asof.date()), "equity_at_rebalance": acct["equity"],
                 "weights": weights.to_dict(), "sleeves": per_sleeve, "shares": target_shares}
        if not args.dry_run:
            state_path.write_text(json.dumps(state, indent=2))
        (live_dir / "signals_latest.json").write_text(json.dumps(
            {"asof": str(asof.date()), "sleeves": details}, indent=2, default=float))
        for name, w in per_sleeve.items():
            append_csv(live_dir / f"sleeve_weights_{name}.csv", {"date": str(asof.date()), **w})
    else:
        state = json.loads(state_path.read_text())
        target_shares = state["shares"]

    orders = plan_orders(target_shares, current, last_px, acct["equity"], config.LIVE["min_trade_weight"])
    print(f"{asof.date()} | equity ${acct['equity']:,.0f} | rebalance day: {is_reb_day} | orders: {len(orders)}")
    if not args.dry_run and orders:
        brk.cancel_open_orders()
    for t, qty, why in orders:
        print(f"  {'BUY ' if qty > 0 else 'SELL'} {abs(qty):>6} {t:<5} ~${abs(qty) * last_px[t]:>10,.0f}  ({why})")
        if not args.dry_run:
            oid = brk.submit(t, qty)
            append_csv(live_dir / "trades.csv", {"date": str(asof.date()), "ticker": t, "qty": qty,
                                                 "ref_price": round(float(last_px[t]), 4),
                                                 "reason": why, "order_id": oid})

    if not args.dry_run:
        acct = brk.account()   # (fake broker fills instantly; Alpaca orders fill next open)
        eq_path = live_dir / "equity.csv"
        row = pd.DataFrame([{"date": str(asof.date()), **acct}])
        if eq_path.exists():
            old = pd.read_csv(eq_path, dtype={"date": str})
            row = pd.concat([old[old["date"] != str(asof.date())], row])
        row.to_csv(eq_path, index=False)
        pos = brk.positions()
        (live_dir / "positions_latest.json").write_text(json.dumps({
            "asof": str(asof.date()),
            "updated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "positions": [{"ticker": t, "qty": q, "price": float(last_px[t]),
                           "value": q * float(last_px[t]),
                           "weight": q * float(last_px[t]) / acct["equity"]} for t, q in pos.items()],
        }, indent=2))


TEST_BROKER = brokers.FakeBroker()

if __name__ == "__main__":
    main()
