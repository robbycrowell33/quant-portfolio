"""Model registry: id -> (target_weights function, config dict).
Every model exposes target_weights(prices, cfg) -> (weights Series, details DataFrame)."""
import config
from models import tsmom, xsmom

REGISTRY = {
    "tsmom": (tsmom.target_weights, config.TSMOM),
    "xsmom": (xsmom.target_weights, config.XSMOM),
}
