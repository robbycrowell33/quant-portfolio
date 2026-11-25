"""Model registry: id -> (target_weights function, config dict).
Every model exposes target_weights(prices, cfg) -> (weights Series, details DataFrame)."""
import config
from models import qlv, tsmom, xsmom

REGISTRY = {
    "tsmom": (tsmom.target_weights, config.TSMOM),
    "xsmom": (xsmom.target_weights, config.XSMOM),
    "qlv": (qlv.target_weights, config.QLV),
}


def required_tickers(model_ids):
    """Tickers that must download for these models to run. For stock-universe models
    only the hedge is required; individual stocks that fail are just skipped."""
    out = set()
    for m in model_ids:
        cfg = REGISTRY[m][1]
        out |= {cfg["hedge"]} if cfg.get("hedge") else set(cfg["universe"])
    return out
