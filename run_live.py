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
from core.portfolio import apply_band
from models import REGISTRY as MODELS

LIVE_DIR = Path("live")


PAPER = [m for m, info in config.MODEL_INFO.items() if info.get("kind") == "signal" and m in MODELS]


def sleeve_due(name, asof, prev_state, force, key="sleeve_asof"):
    """Weekly sleeves rebalance every rebalance day. Monthly sleeves only on the
    first rebalance day of each month (same rule as the backtest)."""
    if force or MODELS[name][1].get("rebalance", "weekly") != "monthly":
        return True
    last = (prev_state or {}).get(key, {}).get(name)
    return last is None or pd.Timestamp(last).to_period("M") != asof.to_period("M")


def combined_targets(prices, asof, cur_w, prev_state, prev_signals, force=False):
    """Sum every sleeve's weights scaled by its capital share. A sleeve that isn't due
    keeps its current holdings (they drift, like in the backtest). Sleeves never share
    tickers, so a sleeve's current holdings are just the account's positions in its universe."""
    total, per_sleeve, details, sleeve_asof = pd.Series(dtype=float), {}, {}, {}
    for name, alloc in config.SLEEVES.items():
        fn, cfg = MODELS[name]
        if sleeve_due(name, asof, prev_state, force):
            w, det = fn(prices[cfg["universe"]], cfg)
            w = w * alloc
            details[name] = det.reset_index(names="ticker").to_dict(orient="records")
            sleeve_asof[name] = str(asof.date())
        else:
            w = cur_w.reindex(cfg["universe"]).fillna(0.0)
            details[name] = prev_signals.get("sleeves", {}).get(name, [])
            sleeve_asof[name] = prev_state["sleeve_asof"][name]
        per_sleeve[name] = w.to_dict()
        total = total.add(w, fill_value=0.0)
    gross = total.abs().sum()
    if gross > config.LIVE["max_gross"]:          # account-level leverage cap
        total *= config.LIVE["max_gross"] / gross
        print(f"  combined gross {gross:.2f} > cap {config.LIVE['max_gross']}, scaled down")
    return total, per_sleeve, details, sleeve_asof


def paper_targets(prices, asof, prev_state, prev_signals, force=False):
    """Paper-only models: same schedule as if live, but weights are only logged.
    Never touches the account. Weights are at standalone scale (100% of capital)."""
    weights, details, paper_asof = {}, {}, {}
    for name in PAPER:
        fn, cfg = MODELS[name]
        if sleeve_due(name, asof, prev_state, force, key="paper_asof"):
            w, det = fn(prices[cfg["universe"]], cfg)
            weights[name] = w.to_dict()
            details[name] = det.reset_index(names="ticker").to_dict(orient="records")
            paper_asof[name] = str(asof.date())
        else:
            weights[name] = prev_state["paper_weights"][name]
            details[name] = prev_signals.get("paper", {}).get(name, [])
            paper_asof[name] = prev_state["paper_asof"][name]
    return weights, details, paper_asof


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
    """Append a row; tolerant of new columns appearing later."""
    df = pd.DataFrame([row])
    if path.exists():
        df = pd.concat([pd.read_csv(path), df], ignore_index=True)
    df.to_csv(path, index=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--asof", help="(test mode) pretend today is this date")
    args = ap.parse_args()

    universe = sorted({t for n in [*config.SLEEVES, *PAPER] for t in MODELS[n][1]["universe"]})
    signals_path_name = "signals_latest.json"
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
        prev_state = json.loads(state_path.read_text()) if state_path.exists() else None
        sig_path = live_dir / signals_path_name
        prev_signals = json.loads(sig_path.read_text()) if sig_path.exists() else {}
        cur_w = pd.Series({t: q * last_px[t] / acct["equity"] for t, q in current.items() if t in last_px},
                          dtype=float)
        weights, per_sleeve, details, sleeve_asof = combined_targets(
            prices, asof, cur_w, prev_state, prev_signals, force=args.force)
        paper_w, paper_det, paper_asof = paper_targets(prices, asof, prev_state, prev_signals, force=args.force)
        # v1.1 no-trade band (same rule as the backtest): positions that are close
        # enough to target keep their current share count.
        banded = apply_band(weights, cur_w, *config.LIVE["band"])
        kept = [t for t in banded.index if t in current and banded[t] == cur_w.get(t)]
        target_shares = to_shares(banded.drop(kept), acct["equity"], last_px)
        target_shares.update({t: current[t] for t in kept})
        if kept:
            print(f"  within no-trade band, holding: {', '.join(sorted(kept))}")
        state = {"asof": str(asof.date()), "equity_at_rebalance": acct["equity"],
                 "weights": weights.to_dict(), "sleeves": per_sleeve, "sleeve_asof": sleeve_asof,
                 "shares": target_shares, "paper_weights": paper_w, "paper_asof": paper_asof}
        if not args.dry_run:
            state_path.write_text(json.dumps(state, indent=2))
            (live_dir / signals_path_name).write_text(json.dumps(
                {"asof": str(asof.date()), "sleeve_asof": sleeve_asof, "sleeves": details,
                 "paper_asof": paper_asof, "paper": paper_det}, indent=2, default=float))
            (live_dir / "paper").mkdir(exist_ok=True)
            for name, w in paper_w.items():
                append_csv(live_dir / "paper" / f"{name}_weights.csv", {"date": str(asof.date()), **w})
            for name, w in per_sleeve.items():   # logged at standalone scale (100% of capital)
                alloc = config.SLEEVES[name]
                append_csv(live_dir / f"sleeve_weights_{name}.csv",
                           {"date": str(asof.date()), **{t: v / alloc for t, v in w.items()}})
        else:
            for name in per_sleeve:
                print(f"  {name}: {'new targets' if sleeve_asof[name] == str(asof.date()) else 'holding (not due)'}")
            for name in paper_w:
                print(f"  {name} (paper only, no orders): {'new signals' if paper_asof[name] == str(asof.date()) else 'not due'}")
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
