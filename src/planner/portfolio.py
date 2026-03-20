from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from src.planner.binance_gateway import BinanceGateway, ms_to_iso, parse_binance_rows
from src.planner.config import load_config
from src.planner.models import PortfolioState, utc_now_iso
from src.planner.storage import PlannerRepository


class PortfolioService:
    def __init__(self, repository: PlannerRepository, gateway: Optional[BinanceGateway] = None, config: Optional[Dict] = None):
        self.repository = repository
        self.gateway = gateway
        self.config = config or load_config()
        self.planner_config = self.config["planner"]

    def _spot_pair_for_asset(self, asset: str, exchange_symbols: Dict[str, Dict]) -> Optional[str]:
        pair = f"{asset}USDT"
        symbol_info = exchange_symbols.get(pair)
        if not symbol_info:
            return None
        if symbol_info.get("status") != "TRADING":
            return None
        if not symbol_info.get("isSpotTradingAllowed", True):
            return None
        return pair

    def _exchange_symbols(self) -> Dict[str, Dict]:
        info = self.gateway.get_exchange_info() if self.gateway else {"symbols": []}
        return {row["symbol"]: row for row in info.get("symbols", [])}

    def _asset_usd_value(self, asset: str, amount: float, exchange_symbols: Dict[str, Dict]) -> float:
        if amount <= 0:
            return 0.0
        if asset == "EUR":
            pair = exchange_symbols.get("EURUSDT")
            return amount * float(self.gateway.get_symbol_ticker("EURUSDT")["price"]) if pair else amount
        if asset in self.planner_config["stable_assets"] or asset == "USDT":
            return amount
        pair = self._spot_pair_for_asset(asset, exchange_symbols)
        if pair:
            return amount * float(self.gateway.get_symbol_ticker(pair)["price"])
        return 0.0

    def _compute_trade_ledger(self, symbol: str, current_qty: float) -> Tuple[float, float, str]:
        if not self.gateway or current_qty <= 0:
            return 0.0, 0.0, "No trade history available"
        trades = self.gateway.get_my_trades(symbol=symbol, limit=1000)
        trades = sorted(trades, key=lambda row: int(row["time"]))
        qty = 0.0
        cost = 0.0
        realized = 0.0
        for trade in trades:
            trade_qty = float(trade["qty"])
            trade_price = float(trade["price"])
            if trade.get("isBuyer"):
                qty += trade_qty
                cost += trade_qty * trade_price
            else:
                if qty <= 0:
                    continue
                avg_cost = cost / qty if qty else 0.0
                sold_qty = min(qty, trade_qty)
                realized += sold_qty * (trade_price - avg_cost)
                qty -= sold_qty
                cost -= avg_cost * sold_qty
        if qty <= 0:
            return 0.0, realized, "No open quantity after trade replay"
        avg_entry = cost / qty
        note = "Derived from Binance spot trade history"
        if abs(qty - current_qty) > max(0.0000001, current_qty * 0.02):
            note = "Trade history qty drift; using current quantity with derived average cost"
        scaled_cost = avg_entry * current_qty
        return scaled_cost, realized, note

    def sync(self) -> PortfolioState:
        if not self.gateway:
            raise RuntimeError("Binance gateway is required for live portfolio sync")

        snapshot_ts = utc_now_iso()
        account = self.gateway.get_account()
        exchange_symbols = self._exchange_symbols()
        balances = account.get("balances", [])
        eurusdt = float(self.gateway.get_symbol_ticker("EURUSDT")["price"])

        free_cash = 0.0
        free_cash_eur = 0.0
        spot_equity = 0.0
        realized_pnl_usd = 0.0
        unrealized_pnl_usd = 0.0
        assets = []
        spot_positions = []
        cash_balances = []

        for balance in balances:
            asset = balance.get("asset")
            free_amount = float(balance.get("free", 0) or 0)
            locked_amount = float(balance.get("locked", 0) or 0)
            qty = free_amount + locked_amount
            if qty <= 0:
                continue

            if asset in self.planner_config["cash_assets"]:
                value_usd = self._asset_usd_value(asset, qty, exchange_symbols)
                value_eur = value_usd / eurusdt if eurusdt else 0.0
                free_cash += value_usd
                free_cash_eur += value_eur
                cash_balances.append(
                    {
                        "asset": asset,
                        "amount": qty,
                        "value_usd": value_usd,
                        "value_eur": value_eur,
                        "bucket_type": "cash",
                        "source_snapshot_ts": snapshot_ts,
                    }
                )
                continue

            pair = self._spot_pair_for_asset(asset, exchange_symbols)
            if not pair:
                continue

            last_price = float(self.gateway.get_symbol_ticker(pair)["price"])
            value_usd = qty * last_price
            cost_usd, realized, note = self._compute_trade_ledger(pair, qty)
            if cost_usd <= 0:
                cost_usd = value_usd
                note = "Cost basis unavailable from trade history; defaulted to mark price"
            entry_price = cost_usd / qty if qty else last_price
            realized_pnl_usd += realized
            position_unrealized = value_usd - cost_usd
            unrealized_pnl_usd += position_unrealized
            spot_equity += value_usd
            assets.append(
                {
                    "symbol": pair,
                    "base_asset": asset,
                    "quote_asset": "USDT",
                    "tags": "[]",
                    "is_major": 1 if asset in self.planner_config["spot_excluded_assets"] else 0,
                    "is_seed": 0,
                    "status": exchange_symbols[pair].get("status", "ACTIVE"),
                    "updated_ts": snapshot_ts,
                }
            )
            spot_positions.append(
                {
                    "symbol": pair,
                    "entry_ts": snapshot_ts,
                    "entry_price": entry_price,
                    "qty": qty,
                    "cost_usd": cost_usd,
                    "stop_price": None,
                    "tp1_price": None,
                    "tp2_price": None,
                    "status": "UNRECONCILED" if "unavailable" in note.lower() else "SYNCED",
                    "max_hold_until": None,
                    "catalyst_event_id": None,
                    "last_price": last_price,
                    "unrealized_pnl_usd": position_unrealized,
                    "realized_pnl_usd": realized,
                    "close_ts": None,
                    "close_price": None,
                    "notes": note,
                }
            )

        earn_positions = []
        earn_equity = 0.0
        locked_cash = 0.0
        accrued_yield_usd = 0.0
        product_rows = parse_binance_rows(self.gateway.get_simple_earn_flexible_product_position(size=100))
        product_rows += parse_binance_rows(self.gateway.get_simple_earn_locked_product_position(size=100))

        for row in product_rows:
            asset = row.get("asset") or row.get("productAsset") or row.get("coin") or row.get("projectId")
            amount = float(row.get("totalAmount") or row.get("amount") or row.get("holdingAmount") or 0.0)
            if amount <= 0:
                continue
            apr = float(row.get("latestAnnualPercentageRate") or row.get("apr") or row.get("annualPercentageRate") or 0.0)
            product_type = str(row.get("productType") or row.get("type") or "FLEXIBLE").upper()
            redeemable = 0 if product_type.startswith("LOCK") else 1
            locked_until = ms_to_iso(row.get("endTime") or row.get("redeemDate"))
            price = 1.0 if asset == "USDT" or asset in self.planner_config["stable_assets"] else float(self.gateway.get_symbol_ticker(symbol=f"{asset}USDT")["price"])
            value_usd = amount * price
            accrued = float(row.get("totalRewardAmt") or row.get("cumulativeTotalRewardAmount") or 0.0) * price
            earn_equity += value_usd
            accrued_yield_usd += accrued
            if redeemable == 0:
                locked_cash += value_usd
            earn_positions.append(
                {
                    "asset": asset,
                    "product_type": product_type,
                    "apr": apr,
                    "amount": amount,
                    "value_usd": value_usd,
                    "locked_until": locked_until,
                    "status": "LOCKED" if redeemable == 0 else "FLEXIBLE",
                    "source_snapshot_ts": snapshot_ts,
                    "accrued_yield_usd": accrued,
                    "auto_subscribe": 0,
                    "redeemable": redeemable,
                }
            )

        total_equity = free_cash + spot_equity + earn_equity
        total_equity_eur = total_equity / eurusdt if eurusdt else 0.0
        min_buffer = total_equity * self.planner_config["min_free_cash_buffer_pct_total_equity"]
        buying_power = max(0.0, free_cash - min_buffer)

        snapshot = {
            "snapshot_ts": snapshot_ts,
            "total_equity": total_equity,
            "total_equity_eur": total_equity_eur,
            "earn_equity": earn_equity,
            "spot_equity": spot_equity,
            "free_cash": free_cash,
            "free_cash_eur": free_cash_eur,
            "locked_cash": locked_cash,
            "buying_power": buying_power,
            "realized_pnl_usd": realized_pnl_usd,
            "unrealized_pnl_usd": unrealized_pnl_usd,
            "accrued_yield_usd": accrued_yield_usd,
        }
        self.repository.upsert_assets(assets)
        self.repository.record_snapshot(snapshot, earn_positions, spot_positions, cash_balances)
        return PortfolioState(**snapshot)

    def recommend_earn_allocations(self) -> List[Dict]:
        snapshot = self.repository.latest_snapshot()
        if not snapshot:
            return []
        positions = self.repository.latest_earn_positions()
        planner = self.planner_config
        recommendations = []
        free_cash = snapshot["free_cash"]
        total_equity = snapshot["total_equity"]
        min_buffer = total_equity * planner["min_free_cash_buffer_pct_total_equity"]
        target_earn = total_equity * planner["earn_target_pct"]
        current_earn = snapshot["earn_equity"]
        if current_earn < target_earn and free_cash > min_buffer:
            deployable = min(free_cash - min_buffer, target_earn - current_earn)
            if deployable > 0:
                recommendations.append(
                    {
                        "ts": snapshot["snapshot_ts"],
                        "sleeve": "earn",
                        "symbol_or_asset": "USDT",
                        "action": "SUBSCRIBE_FLEXIBLE",
                        "priority": 70,
                        "status": "actionable",
                        "reason": f"Idle cash above reserve buffer. Deploy up to ${deployable:,.2f} into flexible Earn.",
                        "capital_required_usd": round(deployable, 2),
                        "expires_ts": None,
                        "metadata_json": "{\"product_type\":\"FLEXIBLE\"}",
                    }
                )
        latest_spot = [
            rec for rec in self.repository.recent_recommendations(limit=20)
            if rec["sleeve"] == "spot" and rec["status"] == "actionable"
        ]
        top_spot_need = max([rec["capital_required_usd"] for rec in latest_spot], default=0.0)
        for position in positions:
            if position["status"] == "LOCKED":
                opportunity_cost = max(0.0, top_spot_need - snapshot["buying_power"])
                reason = (
                    f"Locked until {position['locked_until'] or 'unknown'}. "
                    f"Estimated opportunity cost versus top actionable spot idea: ${opportunity_cost:,.2f}."
                )
                recommendations.append(
                    {
                        "ts": snapshot["snapshot_ts"],
                        "sleeve": "earn",
                        "symbol_or_asset": position["asset"],
                        "action": "HOLD_LOCKED",
                        "priority": 20,
                        "status": "watchlist",
                        "reason": reason,
                        "capital_required_usd": 0.0,
                        "expires_ts": position["locked_until"],
                        "metadata_json": "{\"opportunity_cost\": %.2f}" % opportunity_cost,
                    }
                )
        return recommendations
