import json
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from src.planner.binance_gateway import BinanceGateway
from src.planner.config import load_config
from src.planner.indicators import atr, ema, max_drawdown, pct_change
from src.planner.models import utc_now_iso
from src.planner.storage import PlannerRepository


class BacktestService:
    def __init__(self, repository: PlannerRepository, gateway: Optional[BinanceGateway] = None, config: Optional[Dict] = None):
        self.repository = repository
        self.gateway = gateway
        self.config = config or load_config()

    def _simulate_trade(self, four_hour: List[Dict], start_idx: int, entry_price: float, stop_price: float, tp1: float, tp2: float, trailing_atr: float) -> Dict:
        qty_remaining = 1.0
        realized_r = 0.0
        stop = stop_price
        highest_close = entry_price
        exit_time = four_hour[min(len(four_hour) - 1, start_idx)]["close_time"]
        for candle in four_hour[start_idx: start_idx + 60]:
            exit_time = candle["close_time"]
            highest_close = max(highest_close, candle["close"])
            if qty_remaining >= 1.0 and candle["high"] >= tp1:
                realized_r += 0.33 * ((tp1 / entry_price) - 1.0)
                qty_remaining = 0.67
                stop = max(stop, entry_price)
            if qty_remaining > 0.34 and candle["high"] >= tp2:
                realized_r += 0.33 * ((tp2 / entry_price) - 1.0)
                qty_remaining = 0.34
                stop = max(stop, tp1)
            trailing_stop = max(stop, highest_close - trailing_atr)
            if candle["low"] <= trailing_stop:
                realized_r += qty_remaining * ((trailing_stop / entry_price) - 1.0)
                return {"pnl_pct": realized_r * 100.0, "outcome": "stopped", "exit_time": exit_time}
        final_close = four_hour[min(len(four_hour) - 1, start_idx + 59)]["close"]
        realized_r += qty_remaining * ((final_close / entry_price) - 1.0)
        return {"pnl_pct": realized_r * 100.0, "outcome": "time_exit", "exit_time": exit_time}

    def run_spot_backtest(self, limit_events: Optional[int] = None) -> Dict:
        if not self.gateway:
            raise RuntimeError("Binance gateway is required for live backtests")
        events = self.repository.recent_events(max_age_days=3650)
        if limit_events:
            events = events[:limit_events]

        trades = []
        bucket_counts = {"continuation": 0, "pullback": 0}
        catalyst_counts = {}
        for event in events:
            pair = event["symbol"] if event["symbol"].endswith("USDT") else f"{event['symbol']}USDT"
            event_dt = datetime.fromisoformat(event["event_ts"].replace("Z", "+00:00"))
            start = (event_dt - timedelta(days=15)).strftime("%Y-%m-%d")
            end = (event_dt + timedelta(days=20)).strftime("%Y-%m-%d")
            daily = self.gateway.get_historical_klines(pair, "1d", start, end)
            four_hour = self.gateway.get_historical_klines(pair, "4h", start, end)
            if len(daily) < 25 or len(four_hour) < 40:
                continue

            entered = None
            for idx in range(7, len(daily)):
                candle_dt = datetime.fromtimestamp(daily[idx]["close_time"] / 1000, tz=timezone.utc)
                age_days = (candle_dt - event_dt).total_seconds() / 86400.0
                if age_days < 0 or age_days > 7:
                    continue
                current_price = daily[idx]["close"]
                ret_24h = pct_change(daily[idx]["close"], daily[idx - 1]["close"])
                ret_7d = pct_change(daily[idx]["close"], daily[idx - 7]["close"]) if idx >= 7 else 0.0
                ema_period_1d = min(20, idx + 1)
                ema20_1d = ema([row["close"] for row in daily[: idx + 1]], ema_period_1d)
                if not ema20_1d:
                    continue
                ema20_1d_value = ema20_1d[-1]
                recent_4h = [row for row in four_hour if row["close_time"] <= daily[idx]["close_time"]][-30:]
                if len(recent_4h) < 8:
                    continue
                ema_period_4h = min(20, len(recent_4h))
                ema20_4h = ema([row["close"] for row in recent_4h], ema_period_4h)[-1]
                post_event_daily = [row for row in daily if row["close_time"] >= int(event_dt.timestamp() * 1000) and row["close_time"] <= daily[idx]["close_time"]]
                post_high = max(row["high"] for row in post_event_daily)
                drawdown = ((post_high / current_price) - 1.0) * 100.0
                setup_type = None
                if age_days <= 3 and current_price > ema20_4h and 3.0 <= ret_24h <= 25.0:
                    setup_type = "continuation"
                elif age_days <= 7 and ret_7d > 0 and 5.0 <= drawdown <= 18.0 and current_price > ema20_1d_value:
                    setup_type = "pullback"
                if not setup_type:
                    continue

                swing_low = min(row["low"] for row in recent_4h[-6:])
                stop = min(current_price * 0.92, swing_low)
                trade = self._simulate_trade(
                    four_hour,
                    max(0, len([row for row in four_hour if row["close_time"] <= daily[idx]["close_time"]]) - 1),
                    current_price,
                    stop,
                    current_price * 1.10,
                    current_price * 1.20,
                    atr(recent_4h, 14) * 2,
                )
                trade["setup_type"] = setup_type
                trade["event_type"] = event["event_type"]
                trade["event_age_bucket"] = "day_1_3" if age_days <= 3 else "day_4_7"
                trade["volume_bucket"] = "high_volume" if daily[idx]["quote_volume"] >= 10_000_000 else "low_volume"
                trade["regime"] = "risk_off" if ret_24h < 0 else "risk_on"
                trades.append(trade)
                bucket_counts[setup_type] += 1
                catalyst_counts[event["event_type"]] = catalyst_counts.get(event["event_type"], 0) + 1
                entered = trade
                break

        wins = [t for t in trades if t["pnl_pct"] > 0]
        losses = [t for t in trades if t["pnl_pct"] <= 0]
        pnl_values = [t["pnl_pct"] for t in trades]
        equity_curve = []
        equity = 100.0
        for pnl in pnl_values:
            equity *= (1 + pnl / 100.0)
            equity_curve.append(equity)
        metrics = {
            "trades": len(trades),
            "win_rate_pct": (len(wins) / len(trades) * 100.0) if trades else 0.0,
            "avg_win_pct": (sum(t["pnl_pct"] for t in wins) / len(wins)) if wins else 0.0,
            "avg_loss_pct": (sum(t["pnl_pct"] for t in losses) / len(losses)) if losses else 0.0,
            "expectancy_pct": (sum(pnl_values) / len(pnl_values)) if pnl_values else 0.0,
            "profit_factor": (
                sum(t["pnl_pct"] for t in wins) / abs(sum(t["pnl_pct"] for t in losses))
                if losses and abs(sum(t["pnl_pct"] for t in losses)) > 0
                else None
            ),
            "max_drawdown_pct": max_drawdown(equity_curve),
            "by_setup": bucket_counts,
            "by_catalyst": catalyst_counts,
        }
        self.repository.save_backtest_run(utc_now_iso(), "binance_catalyst_spot", {"limit_events": limit_events}, metrics)
        return metrics
