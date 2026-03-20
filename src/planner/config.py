import json
import os
from copy import deepcopy
from typing import Any, Dict


DEFAULT_CONFIG: Dict[str, Any] = {
    "database_path": "data/journal/dex_analytics.db",
    "planner": {
        "earn_target_pct": 0.70,
        "spot_target_pct": 0.30,
        "spot_max_open_positions": 3,
        "spot_max_position_pct_total_equity": 0.10,
        "spot_max_position_pct_spot_sleeve": 0.33,
        "min_free_cash_buffer_pct_total_equity": 0.20,
        "locked_earn_max_term_days": 30,
        "spot_excluded_assets": ["BTC", "ETH", "BNB"],
        "stable_assets": ["USDT", "USDC", "FDUSD", "TUSD", "DAI", "BUSD", "USDP"],
        "cash_assets": ["USDT", "USDC", "FDUSD", "TUSD", "DAI", "BUSD", "USDP", "EUR"],
        "reporting_currencies": ["USD", "EUR"],
        "event_lookback_days": 7,
        "continuation_max_age_days": 3,
        "pullback_max_age_days": 7,
        "min_quote_volume_usd_24h": 5_000_000,
        "btc_risk_off_daily_return_pct": -4.0,
        "asset_max_extension_above_ema20_pct": 25.0,
    },
}


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(path: str = "config.json") -> Dict[str, Any]:
    config = deepcopy(DEFAULT_CONFIG)
    if os.path.exists(path):
        with open(path, "r") as handle:
            config = _deep_merge(config, json.load(handle))
    return config
