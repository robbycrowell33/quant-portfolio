"""Broker wrapper. AlpacaBroker for paper trading, FakeBroker for offline tests."""
import os


class AlpacaBroker:
    def __init__(self):
        from alpaca.trading.client import TradingClient
        key, secret = os.environ.get("ALPACA_API_KEY"), os.environ.get("ALPACA_SECRET_KEY")
        if not key or not secret:
            raise RuntimeError("Set ALPACA_API_KEY and ALPACA_SECRET_KEY (paper keys).")
        self.client = TradingClient(key, secret, paper=True)   # paper=True: never touches real money

    def account(self):
        a = self.client.get_account()
        return {"equity": float(a.equity), "cash": float(a.cash),
                "long_mv": float(a.long_market_value), "short_mv": float(a.short_market_value),
                "buying_power": float(a.buying_power)}

    def positions(self):
        return {p.symbol: int(float(p.qty)) for p in self.client.get_all_positions()}

    def cancel_open_orders(self):
        self.client.cancel_orders()

    def submit(self, symbol, qty):
        from alpaca.trading.enums import OrderSide, TimeInForce
        from alpaca.trading.requests import MarketOrderRequest
        side = OrderSide.BUY if qty > 0 else OrderSide.SELL
        o = self.client.submit_order(MarketOrderRequest(
            symbol=symbol, qty=abs(qty), side=side, time_in_force=TimeInForce.DAY))
        return str(o.id)


class FakeBroker:
    """In-memory broker that fills instantly at the given prices. For testing only."""
    def __init__(self, cash=100_000.0):
        self.cash, self.pos, self.px = cash, {}, {}

    def account(self):
        mv = {s: q * self.px[s] for s, q in self.pos.items()}
        long_mv = sum(v for v in mv.values() if v > 0)
        short_mv = sum(v for v in mv.values() if v < 0)
        return {"equity": self.cash + long_mv + short_mv, "cash": self.cash,
                "long_mv": long_mv, "short_mv": short_mv, "buying_power": None}

    def positions(self):
        return {s: q for s, q in self.pos.items() if q != 0}

    def cancel_open_orders(self):
        pass

    def submit(self, symbol, qty):
        held = self.pos.get(symbol, 0)
        if held != 0 and (held > 0) != (held + qty > 0) and held + qty != 0:
            raise RuntimeError("flip in one order")   # mimic Alpaca: can't cross zero in one order
        self.pos[symbol] = held + qty
        self.cash -= qty * self.px[symbol]
        return "fake"
