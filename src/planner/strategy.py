import json
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from src.planner.binance_gateway import BinanceGateway
from src.planner.config import load_config
from src.planner.indicators import atr, ema, pct_change
from src.planner.models import PlannerRecommendation, SpotSetup, utc_now_iso
from src.planner.storage import PlannerRepository


class SpotStrategyService:
    def __init__(self, repository: PlannerRepository, gateway: Optional[BinanceGateway] = None, config: Optional[Dict] = None):
        self.repository = repository
        self.gateway = gateway
        self.config = config or load_config()
        self.planner = self.config["planner"]

    def _is_excluded_asset(self, base_asset: str) -> bool:
        if base_asset in self.planner["spot_excluded_assets"]:
            return True
        if base_asset in self.planner["stable_assets"]:
            return True
        for suffix in ("UP", "DOWN", "BULL", "BEAR"):
            if base_asset.endswith(suffix):
                return True
        return False

    def _recent_event_by_symbol(self) -> Dict[str, Dict]:
        events = self.repository.recent_events(self.planner["event_lookback_days"])
        latest = {}
        for event in events:
            symbol = event["symbol"]
            current = latest.get(symbol)
            if not current or (event["event_ts"], event["strength"]) > (current["event_ts"], current["strength"]):
                latest[symbol] = event
        return latest

    @staticmethod
    def _ema_close(candles: List[Dict], period: int = 20) -> float:
        values = ema([c["close"] for c in candles], period)
        return values[-1] if values else 0.0

    def _btc_regime_ok(self) -> bool:
        btc_daily = self.gateway.get_klines("BTCUSDT", "1d", limit=3)
        if len(btc_daily) < 2:
            return True
        ret = pct_change(btc_daily[-1]["close"], btc_daily[-2]["close"])
        return ret > self.planner["btc_risk_off_daily_return_pct"]

    def evaluate_symbol(self, pair: str, event: Dict) -> Optional[SpotSetup]:
        base_asset = pair.replace("USDT", "")
        if self._is_excluded_asset(base_asset):
            return None

        ticker = self.gateway.get_ticker_24h(pair)
        quote_volume = float(ticker.get("quoteVolume", 0) or 0)
        current_price = float(ticker.get("lastPrice", 0) or 0)
        ret_24h = float(ticker.get("priceChangePercent", 0) or 0)

        daily = self.gateway.get_klines(pair, "1d", limit=40)
        four_hour = self.gateway.get_klines(pair, "4h", limit=120)
        if len(daily) < 20 or len(four_hour) < 20 or current_price <= 0:
            return None

        ema20_1d = self._ema_close(daily, 20)
        ema20_4h = self._ema_close(four_hour, 20)
        ret_7d = pct_change(daily[-1]["close"], daily[-8]["close"]) if len(daily) >= 8 else 0.0
        extension_above_ema20_pct = pct_change(current_price, ema20_1d) if ema20_1d else 0.0

        event_ts = datetime.fromisoformat(event["event_ts"].replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        age_days = max(0.0, (now - event_ts).total_seconds() / 86400.0)
        post_event_window = [c for c in daily if c["close_time"] >= event_ts.timestamp() * 1000]
        if not post_event_window:
            post_event_window = daily[-7:]
        post_event_high = max(c["high"] for c in post_event_window)
        drawdown_from_high = ((post_event_high / current_price) - 1.0) * 100.0 if current_price else 0.0

        setup_type = None
        setup_reason = None
        if age_days <= self.planner["continuation_max_age_days"]:
            if (
                current_price > ema20_4h
                and quote_volume >= self.planner["min_quote_volume_usd_24h"]
                and 3.0 <= ret_24h <= 25.0
            ):
                setup_type = "continuation"
                setup_reason = "Recent catalyst with healthy continuation above 4h EMA20."
        if setup_type is None and age_days <= self.planner["pullback_max_age_days"]:
            if (
                ret_7d > 0
                and 5.0 <= drawdown_from_high <= 18.0
                and current_price > ema20_1d
            ):
                setup_type = "pullback"
                setup_reason = "Post-catalyst pullback remains above 1d EMA20 with positive 7d momentum."

        if setup_type is None:
            return None
        if not self._btc_regime_ok():
            return SpotSetup(
                symbol=base_asset,
                pair=pair,
                setup_type=setup_type,
                event_type=event["event_type"],
                event_ts=event["event_ts"],
                event_age_days=age_days,
                entry_price=current_price,
                stop_price=0.0,
                tp1_price=0.0,
                tp2_price=0.0,
                trailing_atr=0.0,
                max_hold_until=(now + timedelta(days=10)).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                quote_volume_usd_24h=quote_volume,
                ret_24h_pct=ret_24h,
                ret_7d_pct=ret_7d,
                extension_above_ema20_pct=extension_above_ema20_pct,
                drawdown_from_post_event_high_pct=drawdown_from_high,
                reason="Rejected: BTC regime is risk-off.",
                passes_market_rules=False,
            )
        if extension_above_ema20_pct > self.planner["asset_max_extension_above_ema20_pct"]:
            return SpotSetup(
                symbol=base_asset,
                pair=pair,
                setup_type=setup_type,
                event_type=event["event_type"],
                event_ts=event["event_ts"],
                event_age_days=age_days,
                entry_price=current_price,
                stop_price=0.0,
                tp1_price=0.0,
                tp2_price=0.0,
                trailing_atr=0.0,
                max_hold_until=(now + timedelta(days=10)).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                quote_volume_usd_24h=quote_volume,
                ret_24h_pct=ret_24h,
                ret_7d_pct=ret_7d,
                extension_above_ema20_pct=extension_above_ema20_pct,
                drawdown_from_post_event_high_pct=drawdown_from_high,
                reason="Rejected: asset is too extended above 1d EMA20.",
                passes_market_rules=False,
            )

        recent_swing_low = min(c["low"] for c in four_hour[-6:])
        fixed_stop = current_price * 0.92
        stop_price = min(fixed_stop, recent_swing_low)
        trailing_atr = atr(four_hour, period=14) * 2
        max_hold_until = (now + timedelta(days=10)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        return SpotSetup(
            symbol=base_asset,
            pair=pair,
            setup_type=setup_type,
            event_type=event["event_type"],
            event_ts=event["event_ts"],
            event_age_days=age_days,
            entry_price=current_price,
            stop_price=stop_price,
            tp1_price=current_price * 1.10,
            tp2_price=current_price * 1.20,
            trailing_atr=trailing_atr,
            max_hold_until=max_hold_until,
            quote_volume_usd_24h=quote_volume,
            ret_24h_pct=ret_24h,
            ret_7d_pct=ret_7d,
            extension_above_ema20_pct=extension_above_ema20_pct,
            drawdown_from_post_event_high_pct=drawdown_from_high,
            reason=setup_reason,
            passes_market_rules=True,
        )

    def scan(self) -> List[Dict]:
        if not self.gateway:
            raise RuntimeError("Binance gateway is required for live spot scans")
        latest_events = self._recent_event_by_symbol()
        snapshot = self.repository.latest_snapshot()
        if not snapshot:
            raise RuntimeError("No portfolio snapshot found. Run `portfolio sync` first.")

        total_equity = snapshot["total_equity"]
        free_cash = snapshot["free_cash"]
        open_positions = self.repository.open_spot_positions()
        reserve_buffer = total_equity * self.planner["min_free_cash_buffer_pct_total_equity"]
        spot_target_equity = total_equity * self.planner["spot_target_pct"]
        max_position_size = min(
            total_equity * self.planner["spot_max_position_pct_total_equity"],
            spot_target_equity * self.planner["spot_max_position_pct_spot_sleeve"],
        )
        rows = []

        for symbol, event in latest_events.items():
            pair = symbol if symbol.endswith("USDT") else f"{symbol}USDT"
            setup = self.evaluate_symbol(pair, event)
            if setup is None:
                continue
            status = "actionable"
            reason = setup.reason
            if not setup.passes_market_rules:
                status = "watchlist"
            elif len(open_positions) >= self.planner["spot_max_open_positions"]:
                status = "blocked"
                reason = f"{reason} Blocked: max open spot positions already reached."
            elif free_cash - reserve_buffer < max_position_size:
                status = "blocked"
                reason = f"{reason} Blocked: free cash buffer would fall below reserve."

            metadata = {
                "pair": setup.pair,
                "setup_type": setup.setup_type,
                "event_type": setup.event_type,
                "event_ts": setup.event_ts,
                "entry_price": setup.entry_price,
                "stop_price": setup.stop_price,
                "tp1_price": setup.tp1_price,
                "tp2_price": setup.tp2_price,
                "trailing_atr": setup.trailing_atr,
                "max_hold_until": setup.max_hold_until,
                "ret_24h_pct": setup.ret_24h_pct,
                "ret_7d_pct": setup.ret_7d_pct,
                "quote_volume_usd_24h": setup.quote_volume_usd_24h,
                "extension_above_ema20_pct": setup.extension_above_ema20_pct,
                "drawdown_from_post_event_high_pct": setup.drawdown_from_post_event_high_pct,
            }
            rows.append(
                {
                    "ts": utc_now_iso(),
                    "sleeve": "spot",
                    "symbol_or_asset": setup.symbol,
                    "action": "BUY_SPOT",
                    "priority": 100 if status == "actionable" else 50,
                    "status": status,
                    "reason": reason,
                    "capital_required_usd": round(max_position_size, 2),
                    "expires_ts": setup.max_hold_until,
                    "metadata_json": json.dumps(metadata),
                }
            )

        self.repository.add_recommendations(rows)
        return rows
