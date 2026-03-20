import json
from datetime import datetime, timedelta, timezone

from src.planner.backtest import BacktestService
from src.planner.events import EventIngestService
from src.planner.portfolio import PortfolioService
from src.planner.reporting import ReportingService
from src.planner.storage import PlannerRepository
from src.planner.strategy import SpotStrategyService


def iso_days_ago(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class FakeGateway:
    def __init__(self, btc_daily_return_pct=-1.0):
        self.btc_daily_return_pct = btc_daily_return_pct

    def get_account(self):
        return {
            "balances": [
                {"asset": "USDT", "free": "300", "locked": "0"},
                {"asset": "EUR", "free": "10", "locked": "0"},
                {"asset": "DOLO", "free": "10", "locked": "0"},
            ]
        }

    def get_exchange_info(self):
        return {
            "symbols": [
                {"symbol": "DOLOUSDT", "status": "TRADING", "isSpotTradingAllowed": True},
                {"symbol": "ENSOUSDT", "status": "TRADING", "isSpotTradingAllowed": True},
                {"symbol": "BTCUSDT", "status": "TRADING", "isSpotTradingAllowed": True},
            ]
        }

    def get_symbol_ticker(self, symbol):
        prices = {"DOLOUSDT": {"price": "12"}, "ENSOUSDT": {"price": "10"}, "BTCUSDT": {"price": "50000"}, "EURUSDT": {"price": "1.1"}}
        return prices[symbol]

    def get_my_trades(self, symbol, limit=1000):
        return [{"time": 1, "qty": "10", "price": "10", "isBuyer": True}]

    def get_simple_earn_flexible_product_position(self, size=100):
        return {
            "rows": [
                {
                    "asset": "USDT",
                    "totalAmount": "50",
                    "apr": "0.12",
                    "productType": "FLEXIBLE",
                    "totalRewardAmt": "1.5",
                }
            ]
        }

    def get_simple_earn_locked_product_position(self, size=100):
        end_time = int((datetime.now(timezone.utc) + timedelta(days=14)).timestamp() * 1000)
        return {
            "rows": [
                {
                    "asset": "USDT",
                    "totalAmount": "200",
                    "apr": "0.20",
                    "productType": "LOCKED",
                    "endTime": end_time,
                    "totalRewardAmt": "4.0",
                }
            ]
        }

    def get_ticker_24h(self, symbol):
        if symbol == "DOLOUSDT":
            return {"quoteVolume": "8000000", "lastPrice": "10", "priceChangePercent": "10"}
        return {"quoteVolume": "9000000", "lastPrice": "10", "priceChangePercent": "4"}

    def get_klines(self, symbol, interval, limit=200):
        if symbol == "BTCUSDT" and interval == "1d":
            prev = 100.0
            current = prev * (1 + self.btc_daily_return_pct / 100.0)
            return [
                {"open_time": 1, "high": prev * 1.01, "low": prev * 0.99, "close": prev, "quote_volume": 0, "close_time": 2},
                {"open_time": 3, "high": current * 1.01, "low": current * 0.99, "close": current, "quote_volume": 0, "close_time": 4},
            ]
        if interval == "4h":
            candles = []
            price = 7.0
            for idx in range(60):
                close = price + (idx * 0.05)
                candles.append(
                    {
                        "open_time": idx * 4,
                        "high": close * 1.02,
                        "low": close * 0.98,
                        "close": close,
                        "quote_volume": 1_000_000,
                        "close_time": idx * 4 + 1,
                    }
                )
            return candles[-limit:]
        candles = []
        price = 6.0
        for idx in range(40):
            close = price + (idx * 0.1)
            candles.append(
                {
                    "open_time": idx * 86400,
                    "high": close * 1.03,
                    "low": close * 0.97,
                    "close": close,
                    "quote_volume": 12_000_000,
                    "close_time": idx * 86400 + 1,
                }
            )
        return candles[-limit:]

    def get_historical_klines(self, symbol, interval, start_str, end_str=None):
        if interval == "1d":
            candles = []
            base = 5.0
            start = datetime(2025, 12, 20, tzinfo=timezone.utc)
            for idx in range(45):
                close = base * (1 + 0.05 * idx)
                candles.append(
                    {
                        "open_time": int((start + timedelta(days=idx)).timestamp() * 1000),
                        "high": close * 1.03,
                        "low": close * 0.97,
                        "close": close,
                        "quote_volume": 11_000_000,
                        "close_time": int((start + timedelta(days=idx, hours=12)).timestamp() * 1000),
                    }
                )
            return candles
        candles = []
        base = 5.0
        start = datetime(2025, 12, 20, tzinfo=timezone.utc)
        for idx in range(220):
            close = base * (1 + 0.008 * idx)
            candles.append(
                {
                    "open_time": int((start + timedelta(hours=4 * idx)).timestamp() * 1000),
                    "high": close * 1.02,
                    "low": close * 0.985,
                    "close": close,
                    "quote_volume": 2_000_000,
                    "close_time": int((start + timedelta(hours=(4 * idx) + 3)).timestamp() * 1000),
                }
            )
        return candles


def test_portfolio_sync_computes_free_cash_and_locked_earn(tmp_path):
    repo = PlannerRepository(str(tmp_path / "planner.db"))
    service = PortfolioService(repo, FakeGateway())
    snapshot = service.sync()

    assert round(snapshot.free_cash, 2) == 310.0
    assert round(snapshot.free_cash_eur, 2) == round(310.0 / 1.1, 2)
    assert snapshot.locked_cash == 200.0
    assert snapshot.spot_equity == 120.0
    assert snapshot.earn_equity == 250.0
    assert round(snapshot.total_equity, 2) == 680.0
    assert round(snapshot.total_equity_eur, 2) == round(680.0 / 1.1, 2)
    assert round(snapshot.buying_power, 2) == 174.0


def test_scan_blocks_candidate_when_reserve_rules_fail(tmp_path):
    repo = PlannerRepository(str(tmp_path / "planner.db"))
    repo.record_snapshot(
        {
            "snapshot_ts": iso_days_ago(0),
            "total_equity": 1000.0,
            "total_equity_eur": 900.0,
            "earn_equity": 700.0,
            "spot_equity": 100.0,
            "free_cash": 150.0,
            "free_cash_eur": 135.0,
            "locked_cash": 200.0,
            "buying_power": 0.0,
            "realized_pnl_usd": 0.0,
            "unrealized_pnl_usd": 0.0,
            "accrued_yield_usd": 0.0,
        },
        [],
        [],
        [],
    )
    EventIngestService(repo).repository.insert_events(
        [
            {
                "symbol": "DOLO",
                "event_type": "alpha_spotlight",
                "source": "manual",
                "event_ts": iso_days_ago(1),
                "headline": "DOLO featured",
                "url": None,
                "strength": 1.0,
            }
        ]
    )
    rows = SpotStrategyService(repo, FakeGateway()).scan()
    assert rows
    assert rows[0]["status"] == "blocked"
    assert "reserve" in rows[0]["reason"].lower()


def test_valid_continuation_setup_has_entry_stop_and_targets(tmp_path):
    repo = PlannerRepository(str(tmp_path / "planner.db"))
    event = {
        "symbol": "DOLO",
        "event_type": "alpha_spotlight",
        "source": "manual",
        "event_ts": iso_days_ago(1),
        "headline": "DOLO featured",
        "url": None,
        "strength": 1.0,
    }
    setup = SpotStrategyService(repo, FakeGateway()).evaluate_symbol("DOLOUSDT", event)
    assert setup is not None
    assert setup.setup_type == "continuation"
    assert setup.passes_market_rules is True
    assert setup.stop_price > 0
    assert setup.tp1_price > setup.entry_price
    assert setup.tp2_price > setup.tp1_price
    assert setup.max_hold_until.endswith("Z")


def test_pullback_or_continuation_is_rejected_in_risk_off_regime(tmp_path):
    repo = PlannerRepository(str(tmp_path / "planner.db"))
    event = {
        "symbol": "DOLO",
        "event_type": "alpha_spotlight",
        "source": "manual",
        "event_ts": iso_days_ago(1),
        "headline": "DOLO featured",
        "url": None,
        "strength": 1.0,
    }
    setup = SpotStrategyService(repo, FakeGateway(btc_daily_return_pct=-5.0)).evaluate_symbol("DOLOUSDT", event)
    assert setup is not None
    assert setup.passes_market_rules is False
    assert "risk-off" in setup.reason.lower()


def test_daily_report_includes_both_sleeves_and_unlocks(tmp_path):
    repo = PlannerRepository(str(tmp_path / "planner.db"))
    snapshot_ts = iso_days_ago(0)
    repo.record_snapshot(
        {
            "snapshot_ts": snapshot_ts,
            "total_equity": 1000.0,
            "total_equity_eur": 900.0,
            "earn_equity": 700.0,
            "spot_equity": 200.0,
            "free_cash": 100.0,
            "free_cash_eur": 90.0,
            "locked_cash": 150.0,
            "buying_power": 0.0,
            "realized_pnl_usd": 25.0,
            "unrealized_pnl_usd": 15.0,
            "accrued_yield_usd": 5.0,
        },
        [
            {
                "asset": "USDT",
                "product_type": "LOCKED",
                "apr": 0.12,
                "amount": 700.0,
                "value_usd": 700.0,
                "locked_until": iso_days_ago(-14),
                "status": "LOCKED",
                "source_snapshot_ts": snapshot_ts,
                "accrued_yield_usd": 5.0,
                "auto_subscribe": 0,
                "redeemable": 0,
            }
        ],
        [
            {
                "symbol": "DOLOUSDT",
                "entry_ts": snapshot_ts,
                "entry_price": 10.0,
                "qty": 20.0,
                "cost_usd": 200.0,
                "stop_price": 9.0,
                "tp1_price": 11.0,
                "tp2_price": 12.0,
                "status": "OPEN",
                "max_hold_until": iso_days_ago(-10),
                "catalyst_event_id": None,
                "last_price": 10.75,
                "unrealized_pnl_usd": 15.0,
                "realized_pnl_usd": 0.0,
                "close_ts": None,
                "close_price": None,
                "notes": "",
            }
        ],
        [
            {
                "asset": "EUR",
                "amount": 20.0,
                "value_usd": 22.0,
                "value_eur": 20.0,
                "bucket_type": "cash",
                "source_snapshot_ts": snapshot_ts,
            }
        ],
    )
    repo.add_recommendations(
        [
            {
                "ts": snapshot_ts,
                "sleeve": "spot",
                "symbol_or_asset": "ENSO",
                "action": "BUY_SPOT",
                "priority": 100,
                "status": "blocked",
                "reason": "Blocked: free cash buffer would fall below reserve.",
                "capital_required_usd": 99.0,
                "expires_ts": iso_days_ago(-5),
                "metadata_json": "{}",
            }
        ]
    )
    text = ReportingService(repo).daily_report_text()
    assert "Earn sleeve" in text
    assert "Spot sleeve" in text
    assert "buying power" in text.lower()
    assert "Cash balances" in text
    assert "EUR 900.00" in text
    assert "Next unlock dates" in text
    assert "Blocked ideas" in text


def test_backtest_outputs_metrics_and_catalyst_breakdown(tmp_path):
    repo = PlannerRepository(str(tmp_path / "planner.db"))
    repo.insert_events(
        [
            {
                "symbol": "DOLO",
                "event_type": "alpha_spotlight",
                "source": "manual",
                "event_ts": "2026-01-01T00:00:00Z",
                "headline": "DOLO featured",
                "url": None,
                "strength": 1.0,
            }
        ]
    )
    metrics = BacktestService(repo, FakeGateway()).run_spot_backtest()
    assert metrics["trades"] >= 1
    assert "profit_factor" in metrics
    assert "by_catalyst" in metrics
    assert metrics["by_catalyst"]["alpha_spotlight"] >= 1


def test_manual_reconciliation_can_insert_and_close_position(tmp_path):
    repo = PlannerRepository(str(tmp_path / "planner.db"))
    payload = {
        "id": None,
        "symbol": "ENSOUSDT",
        "entry_ts": iso_days_ago(2),
        "entry_price": 5.0,
        "qty": 10.0,
        "cost_usd": 50.0,
        "stop_price": 4.6,
        "tp1_price": 5.5,
        "tp2_price": 6.0,
        "status": "OPEN",
        "max_hold_until": iso_days_ago(-8),
        "catalyst_event_id": None,
        "last_price": 5.2,
        "unrealized_pnl_usd": 2.0,
        "realized_pnl_usd": 0.0,
        "close_ts": None,
        "close_price": None,
        "notes": "manual",
    }
    repo.reconcile_spot_position(payload)
    open_rows = repo.open_spot_positions()
    assert len(open_rows) == 1
    close_payload = dict(open_rows[0])
    close_payload.update(
        {
            "status": "CLOSED",
            "close_ts": iso_days_ago(0),
            "close_price": 5.8,
            "realized_pnl_usd": 8.0,
            "unrealized_pnl_usd": 0.0,
        }
    )
    repo.reconcile_spot_position(close_payload)
    assert len(repo.open_spot_positions()) == 0
    assert len(repo.closed_spot_positions()) == 1
