from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Optional


@dataclass
class PlannerRecommendation:
    sleeve: str
    symbol_or_asset: str
    action: str
    priority: int
    status: str
    reason: str
    capital_required_usd: float
    expires_ts: Optional[str] = None
    metadata: Dict = field(default_factory=dict)


@dataclass
class SpotSetup:
    symbol: str
    pair: str
    setup_type: str
    event_type: str
    event_ts: str
    event_age_days: float
    entry_price: float
    stop_price: float
    tp1_price: float
    tp2_price: float
    trailing_atr: float
    max_hold_until: str
    quote_volume_usd_24h: float
    ret_24h_pct: float
    ret_7d_pct: float
    extension_above_ema20_pct: float
    drawdown_from_post_event_high_pct: float
    reason: str
    passes_market_rules: bool


@dataclass
class PortfolioState:
    snapshot_ts: str
    total_equity: float
    total_equity_eur: float
    earn_equity: float
    spot_equity: float
    free_cash: float
    free_cash_eur: float
    locked_cash: float
    buying_power: float
    realized_pnl_usd: float
    unrealized_pnl_usd: float
    accrued_yield_usd: float


def utc_now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
